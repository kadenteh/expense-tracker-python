from __future__ import annotations

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from ..csv_export import expenses_to_csv
from ..models import (
    Filters,
    add_expense,
    delete_expense,
    get_expense,
    list_expenses,
    today_iso,
    update_expense,
    validate_expense,
)
from ..stats import total_of

bp = Blueprint("expenses", __name__, url_prefix="/expenses")


def _filters_from_request() -> Filters:
    return Filters(
        search=request.args.get("q", "").strip(),
        category=request.args.get("category", "All"),
        date_from=request.args.get("from", ""),
        date_to=request.args.get("to", ""),
        sort=request.args.get("sort", "date-desc"),
    )


@bp.route("/")
def list_view():
    filters = _filters_from_request()
    expenses = list_expenses(filters)
    return render_template(
        "expenses/list.html",
        expenses=expenses,
        filters=filters,
        filtered_total=total_of(expenses),
    )


@bp.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        description = request.form.get("description", "")
        amount_raw = request.form.get("amount", "")
        category = request.form.get("category", "")
        expense_date = request.form.get("date", "")

        errors, parsed_amount = validate_expense(description, amount_raw, category, expense_date)
        if errors:
            return render_template(
                "expenses/form.html",
                mode="add",
                errors=errors,
                values={
                    "description": description,
                    "amount": amount_raw,
                    "category": category or "Food",
                    "date": expense_date or today_iso(),
                },
            )

        add_expense(description, parsed_amount, category, expense_date)
        flash("Expense added.", "success")
        return redirect(url_for("expenses.list_view"))

    return render_template(
        "expenses/form.html",
        mode="add",
        errors={},
        values={"description": "", "amount": "", "category": "Food", "date": today_iso()},
    )


@bp.route("/<int:expense_id>/edit", methods=["GET", "POST"])
def edit(expense_id: int):
    expense = get_expense(expense_id)
    if expense is None:
        flash("That expense no longer exists.", "error")
        return redirect(url_for("expenses.list_view"))

    if request.method == "POST":
        description = request.form.get("description", "")
        amount_raw = request.form.get("amount", "")
        category = request.form.get("category", "")
        expense_date = request.form.get("date", "")

        errors, parsed_amount = validate_expense(description, amount_raw, category, expense_date)
        if errors:
            return render_template(
                "expenses/form.html",
                mode="edit",
                expense_id=expense_id,
                errors=errors,
                values={
                    "description": description,
                    "amount": amount_raw,
                    "category": category or "Food",
                    "date": expense_date or today_iso(),
                },
            )

        update_expense(expense_id, description, parsed_amount, category, expense_date)
        flash("Expense updated.", "success")
        return redirect(url_for("expenses.list_view"))

    return render_template(
        "expenses/form.html",
        mode="edit",
        expense_id=expense_id,
        errors={},
        values={
            "description": expense.description,
            "amount": f"{expense.amount:g}",
            "category": expense.category,
            "date": expense.date,
        },
    )


@bp.route("/<int:expense_id>/delete", methods=["POST"])
def delete(expense_id: int):
    expense = get_expense(expense_id)
    if expense is not None:
        delete_expense(expense_id)
        flash(f'Deleted "{expense.description}".', "success")
    return redirect(request.referrer or url_for("expenses.list_view"))


@bp.route("/export.csv")
def export_csv():
    filters = _filters_from_request()
    expenses = list_expenses(filters)
    csv_data = expenses_to_csv(expenses)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )
