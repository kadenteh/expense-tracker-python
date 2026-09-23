"""Lays out an ExportReport as a printable, paginated PDF."""

from __future__ import annotations

from ..categories import CATEGORY_PRINT_RGB
from ..formatting import format_currency, format_date
from ..models import Expense
from .pdf_canvas import PAGE_HEIGHT, PAGE_WIDTH, Color, PdfDocument, PdfPage, fit_text
from .report import ExportReport

MARGIN = 48.0
CONTENT_RIGHT = PAGE_WIDTH - MARGIN
CONTENT_WIDTH = CONTENT_RIGHT - MARGIN
TOP = PAGE_HEIGHT - MARGIN
BOTTOM = 72.0  # rows stop above this; the footer lives below it

INK: Color = (0.07, 0.07, 0.07)
MUTED: Color = (0.42, 0.42, 0.40)
RULE: Color = (0.86, 0.86, 0.83)
HEADER_FILL: Color = (0.955, 0.955, 0.945)
BRAND: Color = (0.165, 0.471, 0.839)

ROW_HEIGHT = 18.0
HEADER_ROW_HEIGHT = 20.0
TOTAL_ROW_HEIGHT = 26.0

# Transaction table columns (left x positions; amount is right-aligned).
COL_DATE = MARGIN + 8
COL_CATEGORY = MARGIN + 92
COL_DESCRIPTION = MARGIN + 196
COL_AMOUNT_RIGHT = CONTENT_RIGHT - 8
DESCRIPTION_WIDTH = COL_AMOUNT_RIGHT - 84 - COL_DESCRIPTION


def render_pdf(report: ExportReport) -> bytes:
    doc = PdfDocument(title="Expense Report", created=report.generated_at)
    page = doc.add_page()
    y = _draw_report_header(page, report)

    if not report.expenses:
        page.text(MARGIN, y - 18, "No expenses match the selected filters.", size=10, color=MUTED)
    else:
        y = _draw_table_header(page, y)
        for expense in report.expenses:
            if y - ROW_HEIGHT < BOTTOM:
                page = doc.add_page()
                y = _draw_table_header(page, _draw_continuation_header(page, report))
            y = _draw_row(page, y, expense)
        if y - TOTAL_ROW_HEIGHT < BOTTOM:
            page = doc.add_page()
            y = _draw_continuation_header(page, report)
        _draw_total_row(page, y, report)

    for number, p in enumerate(doc.pages, start=1):
        _draw_footer(p, report, number, len(doc.pages))
    return doc.to_bytes()


def _rgb(values: tuple[int, int, int]) -> Color:
    return tuple(v / 255 for v in values)  # type: ignore[return-value]


def _generated_label(report: ExportReport) -> str:
    moment = report.generated_at
    time = moment.strftime("%I:%M %p").lstrip("0")
    return f"Generated {format_date(moment.date().isoformat())} at {time}"


def _draw_report_header(page: PdfPage, report: ExportReport) -> float:
    page.rect(MARGIN, TOP - 4, 32, 4, color=BRAND)
    page.text(MARGIN, TOP - 30, "Expense Report", size=22, bold=True, color=INK)
    page.text(MARGIN, TOP - 47, _generated_label(report), size=9, color=MUTED)

    # Key figures.
    y = TOP - 86
    stats = [
        (MARGIN, "RECORDS", f"{report.count:,}"),
        (MARGIN + 110, "TOTAL", format_currency(report.total)),
        (MARGIN + 250, "PERIOD", report.period_label),
    ]
    for x, label, value in stats:
        page.text(x, y + 16, label, size=7.5, bold=True, color=MUTED)
        page.text(x, y, fit_text(value, CONTENT_RIGHT - x, 13, bold=True), size=13, bold=True, color=INK)

    y -= 20
    page.text(
        MARGIN,
        y,
        fit_text(f"Categories: {report.categories_label}", CONTENT_WIDTH, 9),
        size=9,
        color=MUTED,
    )
    y -= 14
    page.line(MARGIN, y, CONTENT_RIGHT, y, color=RULE)

    if report.by_category:
        y = _draw_category_breakdown(page, y - 26, report)

    page.text(MARGIN, y - 30, "Transactions", size=11, bold=True, color=INK)
    return y - 40


def _draw_category_breakdown(page: PdfPage, y: float, report: ExportReport) -> float:
    page.text(MARGIN, y, "Spending by category", size=11, bold=True, color=INK)
    y -= 20
    bar_left = MARGIN + 330
    bar_width = CONTENT_RIGHT - bar_left
    for row in report.by_category:
        color = _rgb(CATEGORY_PRINT_RGB.get(row.category, CATEGORY_PRINT_RGB["Other"]))
        page.rect(MARGIN, y - 0.5, 7, 7, color=color)
        page.text(MARGIN + 14, y, row.category, size=9, color=INK)
        noun = "item" if row.count == 1 else "items"
        page.text_right(MARGIN + 170, y, f"{row.count} {noun}", size=9, color=MUTED)
        page.text_right(MARGIN + 270, y, format_currency(row.total), size=9, bold=True, color=INK)
        page.text_right(MARGIN + 316, y, f"{row.percent:.0f}%", size=9, color=MUTED)
        page.rect(bar_left, y + 1, bar_width, 5, color=HEADER_FILL)
        page.rect(bar_left, y + 1, max(bar_width * row.percent / 100, 1.5), 5, color=color)
        y -= 16
    return y + 4


def _draw_continuation_header(page: PdfPage, report: ExportReport) -> float:
    page.text(MARGIN, TOP - 12, "Expense Report", size=12, bold=True, color=INK)
    page.text_right(CONTENT_RIGHT, TOP - 12, report.period_label, size=9, color=MUTED)
    page.line(MARGIN, TOP - 22, CONTENT_RIGHT, TOP - 22, color=RULE)
    return TOP - 36


def _draw_table_header(page: PdfPage, y: float) -> float:
    page.rect(MARGIN, y - HEADER_ROW_HEIGHT, CONTENT_WIDTH, HEADER_ROW_HEIGHT, color=HEADER_FILL)
    baseline = y - 13
    for x, label in ((COL_DATE, "DATE"), (COL_CATEGORY, "CATEGORY"), (COL_DESCRIPTION, "DESCRIPTION")):
        page.text(x, baseline, label, size=7.5, bold=True, color=MUTED)
    page.text_right(COL_AMOUNT_RIGHT, baseline, "AMOUNT", size=7.5, bold=True, color=MUTED)
    return y - HEADER_ROW_HEIGHT


def _draw_row(page: PdfPage, y: float, expense: Expense) -> float:
    baseline = y - 12.5
    page.text(COL_DATE, baseline, format_date(expense.date), size=9, color=INK)
    page.text(COL_CATEGORY, baseline, expense.category, size=9, color=INK)
    page.text(
        COL_DESCRIPTION, baseline, fit_text(expense.description, DESCRIPTION_WIDTH, 9), size=9, color=INK
    )
    page.text_right(COL_AMOUNT_RIGHT, baseline, format_currency(expense.amount), size=9, color=INK)
    page.line(MARGIN, y - ROW_HEIGHT, CONTENT_RIGHT, y - ROW_HEIGHT, color=RULE)
    return y - ROW_HEIGHT


def _draw_total_row(page: PdfPage, y: float, report: ExportReport) -> None:
    page.line(MARGIN, y, CONTENT_RIGHT, y, width=1, color=INK)
    baseline = y - 17
    noun = "record" if report.count == 1 else "records"
    page.text(COL_DATE, baseline, f"Total · {report.count:,} {noun}", size=10, bold=True, color=INK)
    page.text_right(COL_AMOUNT_RIGHT, baseline, format_currency(report.total), size=10, bold=True, color=INK)


def _draw_footer(page: PdfPage, report: ExportReport, number: int, total: int) -> None:
    page.line(MARGIN, 48, CONTENT_RIGHT, 48, color=RULE)
    page.text(MARGIN, 34, f"Expense Tracker · {_generated_label(report)}", size=8, color=MUTED)
    page.text_right(CONTENT_RIGHT, 34, f"Page {number} of {total}", size=8, color=MUTED)
