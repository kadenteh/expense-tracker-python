"""Export templates: purpose-built reports generated from the expense data.

Every template produces a real file plus a small table and headline figures
that the previews (email, sheet, share page) render.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..formatting import format_currency, format_date
from ..models import CATEGORIES, Expense, all_expenses

PREVIEW_ROW_CAP = 500


@dataclass
class ExportArtifact:
    title: str
    filename: str
    mimetype: str
    content: bytes
    record_count: int
    headers: list[str]
    rows: list[list[str]]
    highlights: list[tuple[str, str]] = field(default_factory=list)
    sensitive_column: Optional[int] = None  # column holding free-text descriptions

    def preview(self) -> dict:
        return {
            "headers": self.headers,
            "rows": self.rows[:PREVIEW_ROW_CAP],
            "row_count": len(self.rows),
            "highlights": self.highlights,
            "sensitive_column": self.sensitive_column,
        }


@dataclass(frozen=True)
class ExportTemplate:
    key: str
    name: str
    tagline: str
    description: str
    icon: str  # name of an inline SVG icon in templates/exports/_icons.html
    periods: Callable[[], list[tuple[str, str]]]
    default_period: Callable[[], str]
    scheduled_period: Callable[[], str]  # the period a recurring run should cover
    build: Callable[[str], ExportArtifact]

    def period_label(self, period: str) -> str:
        return dict(self.periods()).get(period, period)


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


def _recent_months(count: int = 12) -> list[str]:
    current = _month_key(date.today())
    return [_shift_month(current, -i) for i in range(count)]


def _money(amount: float) -> str:
    return f"{amount:.2f}"


def _write_csv(rows: list[list]) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _category_totals(expenses: list[Expense]) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = {}
    for e in expenses:
        buckets.setdefault(e.category, []).append(e.amount)
    return dict(sorted(buckets.items(), key=lambda kv: sum(kv[1]), reverse=True))


def _expense_rows(expenses: list[Expense]) -> list[list[str]]:
    return [[format_date(e.date), e.category, e.description, format_currency(e.amount)] for e in expenses]


EXPENSE_HEADERS = ["Date", "Category", "Description", "Amount"]


# ---------- Tax report ----------


def _tax_periods() -> list[tuple[str, str]]:
    years = {int(e.date[:4]) for e in all_expenses()} | {date.today().year}
    return [(str(y), f"Tax year {y}") for y in sorted(years, reverse=True)]


def _build_tax_report(period: str) -> ExportArtifact:
    expenses = sorted((e for e in all_expenses() if e.date.startswith(period + "-")), key=lambda e: e.date)
    totals = _category_totals(expenses)
    grand_total = sum(e.amount for e in expenses)

    rows: list[list] = [["Tax Report", period], ["Generated", date.today().isoformat()], []]
    rows.append(["Date", "Category", "Description", "Amount"])
    rows += [[e.date, e.category, e.description, _money(e.amount)] for e in expenses]
    rows += [[], ["Category subtotals"], ["Category", "Transactions", "Amount"]]
    rows += [[c, len(a), _money(sum(a))] for c, a in totals.items()]
    rows += [["Total", len(expenses), _money(grand_total)]]

    top = next(iter(totals), None)
    return ExportArtifact(
        title=f"Tax Report · {period}",
        filename=f"tax-report-{period}.csv",
        mimetype="text/csv",
        content=_write_csv(rows),
        record_count=len(expenses),
        headers=EXPENSE_HEADERS,
        rows=_expense_rows(expenses),
        highlights=[
            ("Tax year", period),
            ("Transactions", f"{len(expenses):,}"),
            ("Total", format_currency(grand_total)),
            ("Largest category", top or "—"),
        ],
        sensitive_column=2,
    )


TAX_REPORT = ExportTemplate(
    key="tax-report",
    name="Tax Report",
    tagline="Year-end, accountant-ready",
    description="Every expense for a tax year with category subtotals, ready to hand to your accountant.",
    icon="receipt",
    periods=_tax_periods,
    default_period=lambda: str(date.today().year),
    scheduled_period=lambda: str(date.today().year),
    build=_build_tax_report,
)


# ---------- Monthly summary ----------


def _monthly_periods() -> list[tuple[str, str]]:
    return [(m, _month_label(m)) for m in _recent_months()]


def _build_monthly_summary(period: str) -> ExportArtifact:
    everything = all_expenses()
    month = [e for e in everything if e.date.startswith(period + "-")]
    previous_key = _shift_month(period, -1)
    previous = [e for e in everything if e.date.startswith(previous_key + "-")]

    total = sum(e.amount for e in month)
    previous_total = sum(e.amount for e in previous)
    previous_by_cat = {c: sum(a) for c, a in _category_totals(previous).items()}

    table: list[list[str]] = []
    csv_rows: list[list] = [["Monthly Summary", _month_label(period)], []]
    csv_rows.append(["Category", "Transactions", "Total", "Share", "Previous month", "Change"])
    for category, amounts in _category_totals(month).items():
        cat_total = sum(amounts)
        share = cat_total / total * 100 if total else 0
        before = previous_by_cat.get(category, 0.0)
        change = _percent_change(cat_total, before)
        csv_rows.append([category, len(amounts), _money(cat_total), f"{share:.1f}%", _money(before), change])
        table.append([category, str(len(amounts)), format_currency(cat_total), f"{share:.0f}%", change])
    csv_rows += [[], ["Total", len(month), _money(total), "100%", _money(previous_total), _percent_change(total, previous_total)]]

    busiest = max(month, key=lambda e: e.amount, default=None)
    return ExportArtifact(
        title=f"Monthly Summary · {_month_label(period)}",
        filename=f"monthly-summary-{period}.csv",
        mimetype="text/csv",
        content=_write_csv(csv_rows),
        record_count=len(month),
        headers=["Category", "Transactions", "Total", "Share", "vs. last month"],
        rows=table,
        highlights=[
            ("Month", _month_label(period)),
            ("Spent", format_currency(total)),
            ("vs. last month", _percent_change(total, previous_total)),
            ("Biggest expense", format_currency(busiest.amount) if busiest else "—"),
        ],
    )


def _percent_change(now: float, before: float) -> str:
    if not before:
        return "new" if now else "—"
    change = (now - before) / before * 100
    return f"{change:+.0f}%"


def _previous_month() -> str:
    return _shift_month(_month_key(date.today()), -1)


MONTHLY_SUMMARY = ExportTemplate(
    key="monthly-summary",
    name="Monthly Summary",
    tagline="Where the month went",
    description="Category totals for one month, with the change against the month before.",
    icon="calendar",
    periods=_monthly_periods,
    default_period=lambda: _month_key(date.today()),
    scheduled_period=_previous_month,
    build=_build_monthly_summary,
)


# ---------- Category analysis ----------

_ANALYSIS_WINDOWS = {"3": "Last 3 months", "6": "Last 6 months", "12": "Last 12 months", "all": "All time"}


def _build_category_analysis(period: str) -> ExportArtifact:
    expenses = all_expenses()
    if period != "all":
        first_month = _shift_month(_month_key(date.today()), -(int(period) - 1))
        expenses = [e for e in expenses if e.date[:7] >= first_month]
    total = sum(e.amount for e in expenses)
    months = len({e.date[:7] for e in expenses}) or 1

    table: list[list[str]] = []
    csv_rows: list[list] = [["Category Analysis", _ANALYSIS_WINDOWS[period]], []]
    csv_rows.append(["Category", "Transactions", "Total", "Average", "Largest", "Share", "Monthly average"])
    by_category = _category_totals(expenses)
    for category, amounts in by_category.items():
        cat_total = sum(amounts)
        share = cat_total / total * 100 if total else 0
        csv_rows.append([
            category, len(amounts), _money(cat_total), _money(cat_total / len(amounts)),
            _money(max(amounts)), f"{share:.1f}%", _money(cat_total / months),
        ])
        table.append([
            category, str(len(amounts)), format_currency(cat_total),
            format_currency(cat_total / len(amounts)), format_currency(max(amounts)), f"{share:.0f}%",
        ])
    unused = [c for c in CATEGORIES if c not in by_category]
    if unused:
        csv_rows += [[], ["Unused categories", ", ".join(unused)]]

    return ExportArtifact(
        title=f"Category Analysis · {_ANALYSIS_WINDOWS[period]}",
        filename=f"category-analysis-{period}{'' if period == 'all' else 'm'}.csv",
        mimetype="text/csv",
        content=_write_csv(csv_rows),
        record_count=len(expenses),
        headers=["Category", "Transactions", "Total", "Average", "Largest", "Share"],
        rows=table,
        highlights=[
            ("Window", _ANALYSIS_WINDOWS[period]),
            ("Top category", next(iter(by_category), "—")),
            ("Categories used", f"{len(by_category)} of {len(CATEGORIES)}"),
            ("Monthly average", format_currency(total / months)),
        ],
    )


CATEGORY_ANALYSIS = ExportTemplate(
    key="category-analysis",
    name="Category Analysis",
    tagline="Spot the patterns",
    description="Per-category counts, totals, averages and largest purchases over a rolling window.",
    icon="chart",
    periods=lambda: list(_ANALYSIS_WINDOWS.items()),
    default_period=lambda: "3",
    scheduled_period=lambda: "3",
    build=_build_category_analysis,
)


# ---------- Full backup ----------


def _build_full_backup(period: str) -> ExportArtifact:
    expenses = all_expenses()
    payload = {
        "format": "expense-tracker-backup",
        "version": 1,
        "exported_on": date.today().isoformat(),
        "record_count": len(expenses),
        "expenses": [
            {
                "id": e.id,
                "date": e.date,
                "category": e.category,
                "amount": round(e.amount, 2),
                "description": e.description,
                "created_at": e.created_at,
            }
            for e in expenses
        ],
    }
    total = sum(e.amount for e in expenses)
    return ExportArtifact(
        title="Full Backup",
        filename=f"expense-backup-{date.today().isoformat()}.json",
        mimetype="application/json",
        content=(json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        record_count=len(expenses),
        headers=EXPENSE_HEADERS,
        rows=_expense_rows(expenses),
        highlights=[
            ("Records", f"{len(expenses):,}"),
            ("Total", format_currency(total)),
            ("Oldest", format_date(expenses[-1].date) if expenses else "—"),
            ("Newest", format_date(expenses[0].date) if expenses else "—"),
        ],
        sensitive_column=2,
    )


FULL_BACKUP = ExportTemplate(
    key="full-backup",
    name="Full Backup",
    tagline="Everything, restorable",
    description="Every expense as structured JSON. What scheduled backups and live sync send.",
    icon="archive",
    periods=lambda: [("all", "All data")],
    default_period=lambda: "all",
    scheduled_period=lambda: "all",
    build=_build_full_backup,
)


TEMPLATES: dict[str, ExportTemplate] = {
    t.key: t for t in (TAX_REPORT, MONTHLY_SUMMARY, CATEGORY_ANALYSIS, FULL_BACKUP)
}
