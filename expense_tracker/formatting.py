from __future__ import annotations

from datetime import datetime


def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def format_date(iso_date: str) -> str:
    """e.g. '2026-09-22' -> 'Sep 22, 2026'. Avoids %-d (not portable on Windows)."""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
