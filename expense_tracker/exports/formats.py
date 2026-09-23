"""The export formats. Each one turns an ExportReport into file bytes."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from .csvutil import csv_bytes
from .pdf_report import render_pdf
from .report import ExportReport

CSV_COLUMNS = ["Date", "Category", "Amount", "Description"]
EXPORT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class ExportFormat:
    key: str
    label: str
    extension: str
    mimetype: str
    title: str
    description: str
    render: Callable[[ExportReport], bytes]
    listed: bool = True  # offered in the quick-export dialog
    tabular: bool = False  # a table a spreadsheet can ingest row by row


def render_csv(report: ExportReport) -> bytes:
    rows = [CSV_COLUMNS]
    rows += [[e.date, e.category, f"{e.amount:.2f}", e.description] for e in report.expenses]
    return csv_bytes(rows)


def render_summary_csv(report: ExportReport) -> bytes:
    """The report's display table with its headline figures on top."""
    table = report.display_table
    rows: list[list] = [[report.title]]
    rows += [list(h) for h in table.highlights]
    rows += [[], table.headers, *table.rows]
    return csv_bytes(rows)


def render_json(report: ExportReport) -> bytes:
    options = report.options
    payload = {
        "format": "expense-tracker-export",
        "version": EXPORT_FORMAT_VERSION,
        "title": report.title,
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


ALL_FORMATS: dict[str, ExportFormat] = {
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
            tabular=True,
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
        ExportFormat(
            key="summary",
            label="Summary CSV",
            extension="csv",
            mimetype="text/csv",
            title="Report table",
            description="The template's summary table and headline figures.",
            render=render_summary_csv,
            listed=False,
            tabular=True,
        ),
    )
}

# What the quick-export dialog and /export/* accept.
EXPORT_FORMATS: dict[str, ExportFormat] = {k: f for k, f in ALL_FORMATS.items() if f.listed}
