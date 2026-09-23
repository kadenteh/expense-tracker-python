"""Export templates: named presets on top of the export engine.

A template turns a period ("2026", "2026-09", "3") into engine options (a
date range and sort order), picks which formats make sense, and supplies the
summary table that previews, share pages and the Summary CSV show. The
engine does the querying and file rendering, so every template gets the same
formula-safe CSV, JSON and PDF output.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..exports import ExportOptions, ExportReport, ReportTable, build_report, itemized_table
from ..formatting import format_currency, format_date
from ..models import CATEGORIES, Expense, find_expenses


@dataclass(frozen=True)
class ExportTemplate:
    key: str
    name: str
    tagline: str
    description: str
    icon: str  # name of an inline SVG icon in templates/exports/_icons.html
    formats: tuple[str, ...]  # allowed engine formats; the first is the default
    periods: Callable[[], list[tuple[str, str]]]
    default_period: Callable[[], str]
    scheduled_period: Callable[[], str]  # the period a recurring run should cover
    date_range: Callable[[str], tuple[str, str]]
    filename_stem: Callable[[str], str]
    summarize: Optional[Callable[[ExportReport], ReportTable]] = None  # None: the itemized list
    sort: str = "date-desc"

    def period_label(self, period: str) -> str:
        return dict(self.periods()).get(period, period)

    def title_for(self, period: str) -> str:
        return f"{self.name} · {self.period_label(period)}"

    def options_for(self, period: str, fmt: str) -> ExportOptions:
        date_from, date_to = self.date_range(period)
        return ExportOptions(
            format=fmt, date_from=date_from, date_to=date_to, sort=self.sort, filename=self.filename_stem(period)
        )

    def build(self, period: str, fmt: str) -> ExportReport:
        report = build_report(self.options_for(period, fmt), title=self.title_for(period))
        report.table = self.summarize(report) if self.summarize else itemized_table(report)
        return report


# ---------- Period helpers ----------


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_month(key: str, delta: int) -> str:
    year, month = map(int, key.split("-"))
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _month_label(key: str) -> str:
    year, month = map(int, key.split("-"))
    return date(year, month, 1).strftime("%B %Y")


def _month_range(key: str) -> tuple[str, str]:
    year, month = map(int, key.split("-"))
    return f"{key}-01", f"{key}-{calendar.monthrange(year, month)[1]:02d}"


def _category_totals(expenses: list[Expense]) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = {}
    for e in expenses:
        buckets.setdefault(e.category, []).append(e.amount)
    return dict(sorted(buckets.items(), key=lambda kv: sum(kv[1]), reverse=True))


def _percent_change(now: float, before: float) -> str:
    if not before:
        return "new" if now else "—"
    return f"{(now - before) / before * 100:+.0f}%"


# ---------- Tax report ----------


def _tax_periods() -> list[tuple[str, str]]:
    years = {int(e.date[:4]) for e in find_expenses()} | {date.today().year}
    return [(str(y), f"Tax year {y}") for y in sorted(years, reverse=True)]


def _summarize_tax(report: ExportReport) -> ReportTable:
    table = itemized_table(report)
    top = report.by_category[0].category if report.by_category else "—"
    table.highlights = [
        ("Tax year", report.options.date_from[:4]),
        ("Transactions", f"{report.count:,}"),
        ("Total", format_currency(report.total)),
        ("Largest category", top),
    ]
    return table


TAX_REPORT = ExportTemplate(
    key="tax-report",
    name="Tax Report",
    tagline="Year-end, accountant-ready",
    description="Every expense for a tax year with category subtotals, ready to hand to your accountant.",
    icon="receipt",
    formats=("pdf", "csv", "json"),
    periods=_tax_periods,
    default_period=lambda: str(date.today().year),
    scheduled_period=lambda: str(date.today().year),
    date_range=lambda year: (f"{year}-01-01", f"{year}-12-31"),
    filename_stem=lambda year: f"tax-report-{year}",
    summarize=_summarize_tax,
    sort="date-asc",
)


# ---------- Monthly summary ----------


def _summarize_month(report: ExportReport) -> ReportTable:
    month = report.options.date_from[:7]
    previous_from, previous_to = _month_range(_shift_month(month, -1))
    previous = find_expenses(date_from=previous_from, date_to=previous_to)
    previous_by_cat = {c: sum(a) for c, a in _category_totals(previous).items()}
    previous_total = sum(e.amount for e in previous)

    rows = []
    for c in report.by_category:
        rows.append([
            c.category, str(c.count), format_currency(c.total), f"{c.percent:.0f}%",
            _percent_change(c.total, previous_by_cat.get(c.category, 0.0)),
        ])
    biggest = max(report.expenses, key=lambda e: e.amount, default=None)
    return ReportTable(
        headers=["Category", "Transactions", "Total", "Share", "vs. last month"],
        rows=rows,
        highlights=[
            ("Month", _month_label(month)),
            ("Spent", format_currency(report.total)),
            ("vs. last month", _percent_change(report.total, previous_total)),
            ("Biggest expense", format_currency(biggest.amount) if biggest else "—"),
        ],
    )


MONTHLY_SUMMARY = ExportTemplate(
    key="monthly-summary",
    name="Monthly Summary",
    tagline="Where the month went",
    description="Category totals for one month, with the change against the month before.",
    icon="calendar",
    formats=("summary", "pdf", "csv"),
    periods=lambda: [(m, _month_label(m)) for m in (_shift_month(_month_key(date.today()), -i) for i in range(12))],
    default_period=lambda: _month_key(date.today()),
    scheduled_period=lambda: _shift_month(_month_key(date.today()), -1),
    date_range=_month_range,
    filename_stem=lambda month: f"monthly-summary-{month}",
    summarize=_summarize_month,
)


# ---------- Category analysis ----------

_ANALYSIS_WINDOWS = {"3": "Last 3 months", "6": "Last 6 months", "12": "Last 12 months", "all": "All time"}


def _analysis_range(period: str) -> tuple[str, str]:
    if period == "all":
        return "", ""
    first_month = _shift_month(_month_key(date.today()), -(int(period) - 1))
    return f"{first_month}-01", date.today().isoformat()


def _summarize_categories(report: ExportReport) -> ReportTable:
    months = len({e.date[:7] for e in report.expenses}) or 1
    amounts = _category_totals(report.expenses)
    rows = []
    for c in report.by_category:
        values = amounts[c.category]
        rows.append([
            c.category, str(c.count), format_currency(c.total), format_currency(c.total / c.count),
            format_currency(max(values)), f"{c.percent:.0f}%",
        ])
    window = f"Since {format_date(report.options.date_from)}" if report.options.date_from else "All time"
    return ReportTable(
        headers=["Category", "Transactions", "Total", "Average", "Largest", "Share"],
        rows=rows,
        highlights=[
            ("Window", window),
            ("Top category", rows[0][0] if rows else "—"),
            ("Categories used", f"{len(rows)} of {len(CATEGORIES)}"),
            ("Monthly average", format_currency(report.total / months)),
        ],
    )


CATEGORY_ANALYSIS = ExportTemplate(
    key="category-analysis",
    name="Category Analysis",
    tagline="Spot the patterns",
    description="Per-category counts, totals, averages and largest purchases over a rolling window.",
    icon="chart",
    formats=("summary", "pdf", "json"),
    periods=lambda: list(_ANALYSIS_WINDOWS.items()),
    default_period=lambda: "3",
    scheduled_period=lambda: "3",
    date_range=_analysis_range,
    filename_stem=lambda period: f"category-analysis-{period}{'' if period == 'all' else 'm'}",
    summarize=_summarize_categories,
)


# ---------- Full backup ----------


def _summarize_backup(report: ExportReport) -> ReportTable:
    table = itemized_table(report)
    table.highlights = [
        ("Records", f"{report.count:,}"),
        ("Total", format_currency(report.total)),
        ("Oldest", format_date(report.first_date) if report.first_date else "—"),
        ("Newest", format_date(report.last_date) if report.last_date else "—"),
    ]
    return table


FULL_BACKUP = ExportTemplate(
    key="full-backup",
    name="Full Backup",
    tagline="Everything, restorable",
    description="Every expense as structured JSON. What scheduled backups and live sync send.",
    icon="archive",
    formats=("json", "csv"),
    periods=lambda: [("all", "All data")],
    default_period=lambda: "all",
    scheduled_period=lambda: "all",
    date_range=lambda _period: ("", ""),
    filename_stem=lambda _period: f"expense-backup-{date.today().isoformat()}",
    summarize=_summarize_backup,
)


TEMPLATES: dict[str, ExportTemplate] = {
    t.key: t for t in (TAX_REPORT, MONTHLY_SUMMARY, CATEGORY_ANALYSIS, FULL_BACKUP)
}
