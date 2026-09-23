"""The data behind an export: the selected expenses plus derived summary figures."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import cached_property
from typing import Optional

from ..formatting import format_currency, format_date
from ..models import Expense, find_expenses
from .options import ExportOptions

HIDDEN = "[hidden]"
ITEMIZED_HEADERS = ["Date", "Category", "Description", "Amount"]


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    count: int
    total: float
    percent: float


@dataclass
class ReportTable:
    """What a person sees: the table and headline figures shown in previews,
    share pages, the Summary CSV, and simulated Sheets/email deliveries."""

    headers: list[str]
    rows: list[list[str]]
    highlights: list[tuple[str, str]] = field(default_factory=list)
    sensitive_column: Optional[int] = None  # free-text column hidden when redacting

    def to_dict(self) -> dict:
        return {
            "headers": self.headers,
            "rows": self.rows,
            "row_count": len(self.rows),
            "highlights": [list(h) for h in self.highlights],
            "sensitive_column": self.sensitive_column,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReportTable":
        return cls(
            headers=data["headers"],
            rows=data["rows"],
            highlights=[tuple(h) for h in data.get("highlights", [])],
            sensitive_column=data.get("sensitive_column"),
        )

    def redacted(self) -> "ReportTable":
        column = self.sensitive_column
        if column is None:
            return self
        rows = [[HIDDEN if i == column else cell for i, cell in enumerate(row)] for row in self.rows]
        return replace(self, rows=rows)


@dataclass
class ExportReport:
    options: ExportOptions
    expenses: list[Expense]
    generated_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    title: str = "Expense Report"
    table: Optional[ReportTable] = None  # set by templates; defaults to the itemized list

    @property
    def display_table(self) -> ReportTable:
        return self.table or itemized_table(self)

    @property
    def count(self) -> int:
        return len(self.expenses)

    @cached_property
    def total(self) -> float:
        return round(sum(e.amount for e in self.expenses), 2)

    @cached_property
    def first_date(self) -> Optional[str]:
        return min((e.date for e in self.expenses), default=None)

    @cached_property
    def last_date(self) -> Optional[str]:
        return max((e.date for e in self.expenses), default=None)

    @cached_property
    def by_category(self) -> list[CategoryTotal]:
        """Per-category totals, largest first. Only categories with expenses appear."""
        buckets: dict[str, list[float]] = {}
        for e in self.expenses:
            buckets.setdefault(e.category, []).append(e.amount)
        rows = [
            CategoryTotal(
                category=category,
                count=len(amounts),
                total=round(sum(amounts), 2),
                percent=(sum(amounts) / self.total * 100) if self.total else 0.0,
            )
            for category, amounts in buckets.items()
        ]
        return sorted(rows, key=lambda r: r.total, reverse=True)

    @property
    def period_label(self) -> str:
        """The chosen date range, with open ends filled in from the data itself."""
        start = self.options.date_from or self.first_date
        end = self.options.date_to or self.last_date
        if not start and not end:
            return "No records"
        if not start or not end or start == end:
            return format_date(start or end)
        return f"{format_date(start)} – {format_date(end)}"

    @property
    def categories_label(self) -> str:
        if self.options.all_categories:
            return "All categories"
        return ", ".join(self.options.categories)


def itemized_table(report: ExportReport) -> ReportTable:
    return ReportTable(
        headers=ITEMIZED_HEADERS,
        rows=[[format_date(e.date), e.category, e.description, format_currency(e.amount)] for e in report.expenses],
        highlights=[
            ("Records", f"{report.count:,}"),
            ("Total", format_currency(report.total)),
            ("Period", report.period_label),
        ],
        sensitive_column=2,
    )


def redact_expenses(expenses: list[Expense]) -> list[Expense]:
    """Copies with descriptions hidden, so every renderer masks them for free."""
    return [replace(e, description=HIDDEN) for e in expenses]


def build_report(options: ExportOptions, *, title: str = "Expense Report") -> ExportReport:
    expenses = find_expenses(
        date_from=options.date_from,
        date_to=options.date_to,
        categories=options.categories,
        sort=options.sort,
    )
    return ExportReport(options=options, expenses=expenses, title=title)
