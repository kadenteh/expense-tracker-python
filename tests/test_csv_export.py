from expense_tracker.csv_export import expenses_to_csv
from expense_tracker.models import Expense


def test_expenses_to_csv_format():
    expenses = [
        Expense(1, "Coffee, black", 4.5, "Food", "2026-09-01", "2026-09-01T00:00:00"),
    ]
    csv_text = expenses_to_csv(expenses)
    lines = csv_text.strip().split("\r\n")
    assert lines[0] == "Date,Description,Category,Amount"
    assert lines[1] == '2026-09-01,"Coffee, black",Food,4.50'


def test_expenses_to_csv_empty():
    csv_text = expenses_to_csv([])
    assert csv_text.strip() == "Date,Description,Category,Amount"
