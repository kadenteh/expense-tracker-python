from __future__ import annotations

import csv
import io

from .models import Expense


def expenses_to_csv(expenses: list[Expense]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["Date", "Category", "Amount", "Description"])
    for e in expenses:
        writer.writerow([e.date, e.category, f"{e.amount:.2f}", e.description])
    return buffer.getvalue()
