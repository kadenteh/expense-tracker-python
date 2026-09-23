"""Parsing and validation of export options from request query parameters."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime

from ..models import CATEGORIES, SORT_OPTIONS

FILENAME_MAX_LENGTH = 80

_KNOWN_EXTENSION = re.compile(r"\.(csv|json|pdf)$", re.IGNORECASE)
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")
_REPEATED_DASHES = re.compile(r"-{2,}")


@dataclass(frozen=True)
class ExportOptions:
    format: str = "csv"
    date_from: str = ""
    date_to: str = ""
    categories: tuple[str, ...] = tuple(CATEGORIES)
    sort: str = "date-desc"
    filename: str = ""  # sanitized stem, without extension; empty means use the default

    @property
    def all_categories(self) -> bool:
        return set(self.categories) == set(CATEGORIES)

    def filename_for(self, extension: str) -> str:
        return f"{self.filename or default_filename_stem()}.{extension}"


def default_filename_stem() -> str:
    return f"expenses-{date.today().isoformat()}"


def sanitize_filename(raw: str) -> str:
    """Reduce user input to a safe, portable file stem ('' if nothing usable is left)."""
    stem = _KNOWN_EXTENSION.sub("", (raw or "").strip())
    stem = _UNSAFE_FILENAME_CHARS.sub("-", stem)
    stem = _REPEATED_DASHES.sub("-", stem)
    # Leading dots would make a hidden file; trailing dots/spaces are invalid on Windows.
    stem = stem.strip(" .-")
    return stem[:FILENAME_MAX_LENGTH].rstrip(" .-")


def parse_export_options(
    args: Mapping[str, str], formats: Collection[str]
) -> tuple[ExportOptions, dict[str, str]]:
    """Returns (options, errors). errors maps a field name to a message; empty if valid.

    `categories` is a comma-separated list. When the parameter is absent every
    category is included; when present but empty, that is an error.
    """
    errors: dict[str, str] = {}

    fmt = (args.get("format") or "csv").strip().lower()
    if fmt not in formats:
        errors["format"] = "Choose one of: " + ", ".join(f.upper() for f in formats) + "."

    date_from = _parse_iso_date(args.get("from", ""), "from", errors)
    date_to = _parse_iso_date(args.get("to", ""), "to", errors)
    if date_from and date_to and date_from > date_to:
        errors["to"] = "End date must be on or after the start date."

    raw_categories = args.get("categories")
    if raw_categories is None:
        categories = tuple(CATEGORIES)
    else:
        requested = {c.strip() for c in raw_categories.split(",") if c.strip()}
        unknown = sorted(requested - set(CATEGORIES))
        if unknown:
            errors["categories"] = "Unknown category: " + ", ".join(unknown) + "."
        elif not requested:
            errors["categories"] = "Select at least one category."
        categories = tuple(c for c in CATEGORIES if c in requested)

    sort = args.get("sort") or "date-desc"
    if sort not in SORT_OPTIONS:
        errors["sort"] = "Choose a valid sort order."

    options = ExportOptions(
        format=fmt,
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        sort=sort,
        filename=sanitize_filename(args.get("filename", "")),
    )
    return options, errors


def _parse_iso_date(raw: str, field: str, errors: dict[str, str]) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        errors[field] = "Enter a valid date."
        return ""
