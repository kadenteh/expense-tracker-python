from expense_tracker.csv_export import expenses_to_csv
from expense_tracker.exports.csvutil import csv_bytes, neutralize
from expense_tracker.models import Expense


def test_expenses_to_csv_format():
    expenses = [
        Expense(1, "Coffee, black", 4.5, "Food", "2026-09-01", "2026-09-01T00:00:00"),
    ]
    body = expenses_to_csv(expenses)
    assert body.startswith(b"\xef\xbb\xbf")
    lines = body.decode("utf-8-sig").strip().split("\r\n")
    assert lines[0] == "Date,Category,Amount,Description"
    assert lines[1] == '2026-09-01,Food,4.50,"Coffee, black"'


def test_expenses_to_csv_empty():
    assert expenses_to_csv([]).decode("utf-8-sig").strip() == "Date,Category,Amount,Description"


def test_expenses_to_csv_neutralizes_formulas():
    expenses = [Expense(1, '=HYPERLINK("http://x")', 5, "Food", "2026-09-01", "2026-09-01T00:00:00")]
    assert "'=HYPERLINK" in expenses_to_csv(expenses).decode("utf-8-sig")


def test_neutralize_leaves_signed_numbers_alone():
    assert neutralize("-12.50") == "-12.50"
    assert neutralize("+8%") == "+8%"
    assert neutralize("-1,200.00") == "-1,200.00"
    assert neutralize("-rm -rf") == "'-rm -rf"
    assert neutralize("@SUM(A1)") == "'@SUM(A1)"
    assert neutralize(42) == 42


def test_csv_bytes_is_utf8_with_bom():
    assert csv_bytes([["Café"]]) == "﻿Café\r\n".encode("utf-8")
