from datetime import date

from expense_tracker.models import Expense
from expense_tracker.stats import category_breakdown, expenses_in_month, monthly_trend, total_of


def make_expense(id_, description, amount, category, expense_date):
    return Expense(
        id=id_,
        description=description,
        amount=amount,
        category=category,
        date=expense_date,
        created_at="2026-01-01T00:00:00",
    )


def test_total_of_sums_amounts():
    expenses = [
        make_expense(1, "A", 10.5, "Food", "2026-01-01"),
        make_expense(2, "B", 4.25, "Food", "2026-01-02"),
    ]
    assert total_of(expenses) == 14.75


def test_total_of_empty_is_zero():
    assert total_of([]) == 0


def test_expenses_in_month_filters_correctly():
    expenses = [
        make_expense(1, "A", 10, "Food", "2026-09-05"),
        make_expense(2, "B", 20, "Food", "2026-08-31"),
        make_expense(3, "C", 30, "Food", "2026-09-30"),
    ]
    result = expenses_in_month(expenses, 2026, 9)
    assert {e.id for e in result} == {1, 3}


def test_category_breakdown_sorted_desc_with_percent():
    expenses = [
        make_expense(1, "A", 75, "Entertainment", "2026-09-01"),
        make_expense(2, "B", 25, "Food", "2026-09-01"),
    ]
    breakdown = category_breakdown(expenses)
    assert [c.category for c in breakdown] == ["Entertainment", "Food"]
    assert breakdown[0].percent == 75.0
    assert breakdown[1].percent == 25.0


def test_category_breakdown_excludes_zero_categories():
    expenses = [make_expense(1, "A", 10, "Food", "2026-09-01")]
    breakdown = category_breakdown(expenses)
    assert len(breakdown) == 1
    assert breakdown[0].category == "Food"


def test_category_breakdown_empty():
    assert category_breakdown([]) == []


def test_monthly_trend_buckets_six_months_ending_current():
    expenses = [make_expense(1, "A", 50, "Food", date.today().isoformat())]
    trend = monthly_trend(expenses, months_back=6)
    assert len(trend) == 6
    assert trend[-1].total == 50
    today = date.today()
    assert trend[-1].year == today.year
    assert trend[-1].month == today.month
