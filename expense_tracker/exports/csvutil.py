"""The one CSV writer every export goes through.

It adds a UTF-8 BOM (so Excel reads non-ASCII text correctly) and stops
spreadsheet apps from executing cell text as a formula ("CSV injection").
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence

# Spreadsheet apps evaluate cells starting with these as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# ...but signed numbers and percentages ("-12.50", "+8%") are data, not formulas.
_SIGNED_NUMBER = re.compile(r"[+-]\d[\d,]*(\.\d+)?%?")


def neutralize(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES) and not _SIGNED_NUMBER.fullmatch(value):
        return "'" + value
    return value


def csv_bytes(rows: Iterable[Sequence[object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in rows:
        writer.writerow([neutralize(cell) for cell in row])
    return buffer.getvalue().encode("utf-8-sig")
