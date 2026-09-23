from __future__ import annotations

import csv
import io

from .models import Expense


def expenses_to_csv(expenses: list[Expense]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["Date", "Description", "Category", "Amount"])
    for e in expenses:
        writer.writerow([e.date, e.description, e.category, f"{e.amount:.2f}"])
    return buffer.getvalue()
