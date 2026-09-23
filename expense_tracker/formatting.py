from __future__ import annotations

from datetime import datetime, timezone


def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def format_date(iso_date: str) -> str:
    """e.g. '2026-09-22' -> 'Sep 22, 2026'. Avoids %-d (not portable on Windows)."""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def format_relative(moment: datetime | None, now: datetime | None = None) -> str:
    """'just now', '5 min ago', 'in 3 days'... for timezone-aware datetimes."""
    if moment is None:
        return "never"
    now = now or datetime.now(timezone.utc)
    seconds = (now - moment).total_seconds()
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 45:
        return "in a moment" if future else "just now"
    for limit, size, unit in ((3600, 60, "min"), (86400, 3600, "hr"), (86400 * 30, 86400, "day")):
        if seconds < limit:
            n = max(1, round(seconds / size))
            label = f"{n} {unit}" + ("s" if unit == "day" and n != 1 else "")
            return f"in {label}" if future else f"{label} ago"
    return format_date(moment.astimezone().date().isoformat())


def format_local(moment: datetime | None) -> str:
    """Absolute local time, e.g. 'Sep 22, 2026, 3:04 PM'."""
    if moment is None:
        return ""
    local = moment.astimezone()
    return f"{format_date(local.date().isoformat())}, {local.strftime('%I:%M %p').lstrip('0')}"
