from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from .db import get_db

CATEGORIES = ["Food", "Transportation", "Entertainment", "Shopping", "Bills", "Other"]

SORT_OPTIONS = {
    "date-desc": "date DESC, created_at DESC",
    "date-asc": "date ASC, created_at ASC",
    "amount-desc": "amount DESC",
    "amount-asc": "amount ASC",
}


@dataclass
class Expense:
    id: int
    description: str
    amount: float
    category: str
    date: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Expense":
        return cls(
            id=row["id"],
            description=row["description"],
            amount=row["amount"],
            category=row["category"],
            date=row["date"],
            created_at=row["created_at"],
        )


@dataclass
class Filters:
    search: str = ""
    category: str = "All"
    date_from: str = ""
    date_to: str = ""
    sort: str = "date-desc"


def validate_expense(
    description: str, amount_raw: str, category: str, date_raw: str
) -> tuple[dict, Optional[float]]:
    """Returns (errors, parsed_amount). errors is empty dict if valid."""
    errors: dict[str, str] = {}

    description = (description or "").strip()
    if not description:
        errors["description"] = "Description is required."
    elif len(description) > 120:
        errors["description"] = "Keep it under 120 characters."

    parsed_amount: Optional[float] = None
    try:
        parsed_amount = float(amount_raw)
    except (TypeError, ValueError):
        errors["amount"] = "Enter a valid amount."
    else:
        if parsed_amount <= 0:
            errors["amount"] = "Amount must be greater than $0."
        elif parsed_amount > 1_000_000:
            errors["amount"] = "That amount looks too large."

    if category not in CATEGORIES:
        errors["category"] = "Choose a valid category."

    date_raw = (date_raw or "").strip()
    if not date_raw:
        errors["date"] = "Date is required."
    else:
        try:
            datetime.strptime(date_raw, "%Y-%m-%d")
        except ValueError:
            errors["date"] = "Enter a valid date."

    return errors, parsed_amount


def list_expenses(filters: Filters) -> list[Expense]:
    db = get_db()
    clauses = []
    params: list = []

    if filters.search:
        clauses.append("LOWER(description) LIKE ?")
        params.append(f"%{filters.search.lower()}%")
    if filters.category and filters.category != "All":
        clauses.append("category = ?")
        params.append(filters.category)
    if filters.date_from:
        clauses.append("date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("date <= ?")
        params.append(filters.date_to)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = SORT_OPTIONS.get(filters.sort, SORT_OPTIONS["date-desc"])
    sql = f"SELECT * FROM expenses {where} ORDER BY {order}"
    rows = db.execute(sql, params).fetchall()
    return [Expense.from_row(r) for r in rows]


def get_expense(expense_id: int) -> Optional[Expense]:
    db = get_db()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return Expense.from_row(row) if row else None


def add_expense(description: str, amount: float, category: str, expense_date: str) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO expenses (description, amount, category, date, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (description.strip(), amount, category, expense_date, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return cur.lastrowid


def update_expense(
    expense_id: int, description: str, amount: float, category: str, expense_date: str
) -> None:
    db = get_db()
    db.execute(
        "UPDATE expenses SET description = ?, amount = ?, category = ?, date = ? WHERE id = ?",
        (description.strip(), amount, category, expense_date, expense_id),
    )
    db.commit()


def delete_expense(expense_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()


def all_expenses() -> list[Expense]:
    db = get_db()
    rows = db.execute("SELECT * FROM expenses ORDER BY date DESC, created_at DESC").fetchall()
    return [Expense.from_row(r) for r in rows]


def today_iso() -> str:
    return date.today().isoformat()
