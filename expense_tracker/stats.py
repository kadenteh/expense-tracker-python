from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .models import CATEGORIES, Expense

DONUT_SIZE = 200
DONUT_STROKE = 28
DONUT_RADIUS = (DONUT_SIZE - DONUT_STROKE) / 2
DONUT_CIRCUMFERENCE = 2 * math.pi * DONUT_RADIUS


def total_of(expenses: list[Expense]) -> float:
    return sum(e.amount for e in expenses)


def expenses_in_month(expenses: list[Expense], year: int, month: int) -> list[Expense]:
    out = []
    for e in expenses:
        y, m, _ = e.date.split("-")
        if int(y) == year and int(m) == month:
            out.append(e)
    return out


@dataclass
class CategoryTotal:
    category: str
    total: float
    count: int
    percent: float
    dash_array: str = ""
    dash_offset: float = 0.0


def category_breakdown(expenses: list[Expense]) -> list[CategoryTotal]:
    total = total_of(expenses)
    sums = {c: 0.0 for c in CATEGORIES}
    counts = {c: 0 for c in CATEGORIES}
    for e in expenses:
        sums[e.category] += e.amount
        counts[e.category] += 1

    entries = [
        CategoryTotal(
            category=c,
            total=sums[c],
            count=counts[c],
            percent=(sums[c] / total * 100) if total > 0 else 0,
        )
        for c in CATEGORIES
        if counts[c] > 0
    ]
    entries.sort(key=lambda e: e.total, reverse=True)

    cumulative = 0.0
    for entry in entries:
        fraction = entry.percent / 100
        entry.dash_array = f"{fraction * DONUT_CIRCUMFERENCE:.4f} {DONUT_CIRCUMFERENCE:.4f}"
        entry.dash_offset = -cumulative * DONUT_CIRCUMFERENCE
        cumulative += fraction

    return entries


@dataclass
class MonthTotal:
    year: int
    month: int  # 1-indexed
    total: float
    label: str
    bar_height: float = 0.0


def monthly_trend(expenses: list[Expense], months_back: int = 6, chart_height: int = 132) -> list[MonthTotal]:
    today = date.today()
    buckets: list[MonthTotal] = []
    y, m = today.year, today.month
    months: list[tuple[int, int]] = []
    for _ in range(months_back):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()

    for year, month in months:
        buckets.append(
            MonthTotal(
                year=year,
                month=month,
                total=0.0,
                label=date(year, month, 1).strftime("%b"),
            )
        )

    for e in expenses:
        ey, em, _ = e.date.split("-")
        for bucket in buckets:
            if bucket.year == int(ey) and bucket.month == int(em):
                bucket.total += e.amount
                break

    max_total = max((b.total for b in buckets), default=0) or 1
    for bucket in buckets:
        bucket.bar_height = max(3, (bucket.total / max_total) * (chart_height - 24))

    return buckets
