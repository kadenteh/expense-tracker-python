from __future__ import annotations

from datetime import date

from flask import Blueprint, render_template

from ..models import all_expenses
from ..stats import category_breakdown, expenses_in_month, monthly_trend, total_of

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    expenses = all_expenses()
    today = date.today()

    total = total_of(expenses)
    month_expenses = expenses_in_month(expenses, today.year, today.month)
    month_total = total_of(month_expenses)
    breakdown = category_breakdown(expenses)
    trend = monthly_trend(expenses, months_back=6)
    recent = expenses[:5]

    return render_template(
        "dashboard.html",
        expenses=expenses,
        total=total,
        month_total=month_total,
        breakdown=breakdown,
        top_category=breakdown[0] if breakdown else None,
        trend=trend,
        max_trend_total=max((b.total for b in trend), default=0),
        recent=recent,
    )
