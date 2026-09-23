"""The data behind an export: the selected expenses plus derived summary figures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import Optional

from ..formatting import format_date
from ..models import Expense, find_expenses
from .options import ExportOptions


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    count: int
    total: float
    percent: float


@dataclass
class ExportReport:
    options: ExportOptions
    expenses: list[Expense]
    generated_at: datetime = field(default_factory=lambda: datetime.now().astimezone())

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


def build_report(options: ExportOptions) -> ExportReport:
    expenses = find_expenses(
        date_from=options.date_from,
        date_to=options.date_to,
        categories=options.categories,
        sort=options.sort,
    )
    return ExportReport(options=options, expenses=expenses)
