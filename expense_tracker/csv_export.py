from __future__ import annotations

from .exports.csvutil import csv_bytes
from .exports.formats import CSV_COLUMNS
from .models import Expense


def expenses_to_csv(expenses: list[Expense]) -> bytes:
    """The Expenses page export: same columns and safety rules as every other CSV."""
    rows = [CSV_COLUMNS]
    rows += [[e.date, e.category, f"{e.amount:.2f}", e.description] for e in expenses]
    return csv_bytes(rows)
