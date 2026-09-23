"""The export formats. Each one turns an ExportReport into file bytes."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from dataclasses import dataclass

from .pdf_report import render_pdf
from .report import ExportReport

CSV_COLUMNS = ["Date", "Category", "Amount", "Description"]

# Spreadsheet apps evaluate cells starting with these as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class ExportFormat:
    key: str
    label: str
    extension: str
    mimetype: str
    title: str
    description: str
    render: Callable[[ExportReport], bytes]


def _neutralize_formula(value: str) -> str:
    """Stop a description like '=HYPERLINK(...)' being run as a formula when opened in Excel."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def render_csv(report: ExportReport) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for e in report.expenses:
        writer.writerow([e.date, e.category, f"{e.amount:.2f}", _neutralize_formula(e.description)])
    # The BOM makes Excel detect UTF-8 instead of mangling non-ASCII descriptions.
    return buffer.getvalue().encode("utf-8-sig")


def render_json(report: ExportReport) -> bytes:
    options = report.options
    payload = {
        "export": {
            "generated_at": report.generated_at.isoformat(timespec="seconds"),
            "filters": {
                "date_from": options.date_from or None,
                "date_to": options.date_to or None,
                "categories": list(options.categories),
                "sort": options.sort,
            },
        },
        "summary": {
            "record_count": report.count,
            "total_amount": report.total,
            "first_date": report.first_date,
            "last_date": report.last_date,
            "by_category": [
                {"category": c.category, "count": c.count, "total": c.total} for c in report.by_category
            ],
        },
        "expenses": [
            {
                "id": e.id,
                "date": e.date,
                "category": e.category,
                "amount": round(e.amount, 2),
                "description": e.description,
            }
            for e in report.expenses
        ],
    }
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


EXPORT_FORMATS: dict[str, ExportFormat] = {
    f.key: f
    for f in (
        ExportFormat(
            key="csv",
            label="CSV",
            extension="csv",
            mimetype="text/csv",
            title="Spreadsheet",
            description="Opens in Excel, Numbers, or Google Sheets.",
            render=render_csv,
        ),
        ExportFormat(
            key="json",
            label="JSON",
            extension="json",
            mimetype="application/json",
            title="Structured data",
            description="With a summary block; for scripts and backups.",
            render=render_json,
        ),
        ExportFormat(
            key="pdf",
            label="PDF",
            extension="pdf",
            mimetype="application/pdf",
            title="Printable report",
            description="Summary, category breakdown, and itemized table.",
            render=render_pdf,
        ),
    )
}
