from expense_tracker.models import validate_expense


def test_valid_expense_has_no_errors():
    errors, amount = validate_expense("Coffee", "4.50", "Food", "2026-09-01")
    assert errors == {}
    assert amount == 4.5


def test_empty_description_is_rejected():
    errors, _ = validate_expense("", "4.50", "Food", "2026-09-01")
    assert "description" in errors


def test_negative_amount_is_rejected():
    errors, _ = validate_expense("Coffee", "-1", "Food", "2026-09-01")
    assert "amount" in errors


def test_zero_amount_is_rejected():
    errors, _ = validate_expense("Coffee", "0", "Food", "2026-09-01")
    assert "amount" in errors


def test_non_numeric_amount_is_rejected():
    errors, _ = validate_expense("Coffee", "abc", "Food", "2026-09-01")
    assert "amount" in errors


def test_invalid_category_is_rejected():
    errors, _ = validate_expense("Coffee", "4.50", "Not A Category", "2026-09-01")
    assert "category" in errors


def test_missing_date_is_rejected():
    errors, _ = validate_expense("Coffee", "4.50", "Food", "")
    assert "date" in errors


def test_malformed_date_is_rejected():
    errors, _ = validate_expense("Coffee", "4.50", "Food", "09/01/2026")
    assert "date" in errors
