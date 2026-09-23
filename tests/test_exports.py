import json
import re
from datetime import date, datetime, timezone

import pytest

from expense_tracker.exports import (
    EXPORT_FORMATS,
    ExportOptions,
    ExportReport,
    parse_export_options,
    sanitize_filename,
)
from expense_tracker.exports.pdf_canvas import (
    _HELVETICA_BOLD_WIDTHS,
    _HELVETICA_WIDTHS,
    fit_text,
    text_width,
)
from expense_tracker.models import CATEGORIES, Expense

GENERATED_AT = datetime(2026, 9, 23, 14, 5, tzinfo=timezone.utc)


def make_report(expenses, **option_overrides):
    return ExportReport(
        options=ExportOptions(**option_overrides), expenses=expenses, generated_at=GENERATED_AT
    )


def expense(i=1, description="Coffee", amount=4.5, category="Food", day="2026-09-01"):
    return Expense(i, description, amount, category, day, f"{day}T00:00:00")


def add(client, description, amount, category, day):
    client.post(
        "/expenses/add",
        data={"description": description, "amount": str(amount), "category": category, "date": day},
    )


# ---------- Option parsing ----------


def test_parse_defaults_to_csv_all_categories():
    options, errors = parse_export_options({}, EXPORT_FORMATS)
    assert errors == {}
    assert options.format == "csv"
    assert options.categories == tuple(CATEGORIES)
    assert options.all_categories


def test_parse_categories_are_canonical_order_and_deduplicated():
    options, errors = parse_export_options({"categories": "Bills, Food,Bills"}, EXPORT_FORMATS)
    assert errors == {}
    assert options.categories == ("Food", "Bills")
    assert not options.all_categories


@pytest.mark.parametrize(
    "args, field",
    [
        ({"format": "xlsx"}, "format"),
        ({"from": "2026-13-01"}, "from"),
        ({"to": "not-a-date"}, "to"),
        ({"from": "2026-09-10", "to": "2026-09-01"}, "to"),
        ({"categories": ""}, "categories"),
        ({"categories": "Food,Rent"}, "categories"),
        ({"sort": "random"}, "sort"),
    ],
)
def test_parse_rejects_invalid_input(args, field):
    _, errors = parse_export_options(args, EXPORT_FORMATS)
    assert field in errors


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Q3 report", "Q3 report"),
        ("q3-report.pdf", "q3-report"),
        ("../../etc/passwd", "etc-passwd"),
        ('bad<>:"|?*name', "bad-name"),
        ("  ...hidden  ", "hidden"),
        ("", ""),
        ("x" * 200, "x" * 80),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_filename_falls_back_to_dated_default():
    assert ExportOptions().filename_for("pdf") == f"expenses-{date.today().isoformat()}.pdf"
    assert ExportOptions(filename="taxes").filename_for("csv") == "taxes.csv"


# ---------- Report ----------


def test_report_summary_figures():
    report = make_report(
        [
            expense(1, amount=30, category="Bills", day="2026-09-05"),
            expense(2, amount=10, category="Food", day="2026-08-01"),
            expense(3, amount=20, category="Bills", day="2026-09-20"),
        ]
    )
    assert report.count == 3
    assert report.total == 60
    assert (report.first_date, report.last_date) == ("2026-08-01", "2026-09-20")
    assert [(c.category, c.count, c.total) for c in report.by_category] == [("Bills", 2, 50), ("Food", 1, 10)]
    assert report.period_label == "Aug 1, 2026 – Sep 20, 2026"


def test_report_period_prefers_chosen_range():
    report = make_report([], date_from="2026-01-01", date_to="2026-03-31")
    assert report.period_label == "Jan 1, 2026 – Mar 31, 2026"
    assert make_report([]).period_label == "No records"


# ---------- CSV / JSON ----------


def test_csv_has_bom_columns_and_quoting():
    body = EXPORT_FORMATS["csv"].render(make_report([expense(description="Coffee, black")]))
    assert body.startswith(b"\xef\xbb\xbf")
    lines = body.decode("utf-8-sig").split("\r\n")
    assert lines[0] == "Date,Category,Amount,Description"
    assert lines[1] == '2026-09-01,Food,4.50,"Coffee, black"'


def test_csv_neutralizes_spreadsheet_formulas():
    body = EXPORT_FORMATS["csv"].render(make_report([expense(description="=HYPERLINK(\"x\")")]))
    assert "'=HYPERLINK" in body.decode("utf-8-sig")


def test_json_structure():
    report = make_report(
        [expense(7, description="Café", amount=12.345)], categories=("Food",), date_from="2026-09-01"
    )
    data = json.loads(EXPORT_FORMATS["json"].render(report))
    assert data["export"]["filters"] == {
        "date_from": "2026-09-01",
        "date_to": None,
        "categories": ["Food"],
        "sort": "date-desc",
    }
    assert data["summary"]["record_count"] == 1
    assert data["summary"]["by_category"] == [{"category": "Food", "count": 1, "total": 12.35}]
    assert data["expenses"] == [
        {"id": 7, "date": "2026-09-01", "category": "Food", "amount": 12.35, "description": "Café"}
    ]


# ---------- PDF ----------


def pdf_text(body: bytes) -> str:
    return body.decode("latin-1")


def assert_valid_pdf_structure(body: bytes) -> int:
    """Checks the xref table points at every object; returns the page count."""
    assert body.startswith(b"%PDF-1.4")
    assert body.rstrip().endswith(b"%%EOF")
    startxref = int(re.search(rb"startxref\n(\d+)\n", body).group(1))
    assert body[startxref:].startswith(b"xref")
    offsets = [int(m) for m in re.findall(rb"(\d{10}) 00000 n ", body[startxref:])]
    for number, offset in enumerate(offsets, start=1):
        assert body[offset:].startswith(b"%d 0 obj" % number)
    for match in re.finditer(rb"<< /Length (\d+) >>\nstream\n", body):
        length = int(match.group(1))
        assert body[match.end() + length :].startswith(b"\nendstream")
    return int(re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", body).group(1))


def test_pdf_single_page_contents():
    report = make_report([expense(description="Lunch (team)"), expense(2, category="Bills", amount=100)])
    body = EXPORT_FORMATS["pdf"].render(report)
    assert assert_valid_pdf_structure(body) == 1
    text = pdf_text(body)
    assert "(Expense Report)" in text
    assert r"(Lunch \(team\))" in text  # parentheses escaped
    assert "($104.50)" in text
    assert "(Page 1 of 1)" in text
    assert "(Spending by category)" in text


def test_pdf_paginates_long_reports():
    expenses = [expense(i, description=f"Item {i}", day="2026-09-01") for i in range(1, 121)]
    body = EXPORT_FORMATS["pdf"].render(make_report(expenses))
    pages = assert_valid_pdf_structure(body)
    assert pages >= 3
    text = pdf_text(body)
    assert f"(Page {pages} of {pages})" in text
    assert "(Item 120)" in text
    assert text.count("(DESCRIPTION)") == pages  # table header repeats on each page


def test_pdf_empty_report():
    body = EXPORT_FORMATS["pdf"].render(make_report([]))
    assert assert_valid_pdf_structure(body) == 1
    assert "(No expenses match the selected filters.)" in pdf_text(body)


def test_pdf_encodes_non_ascii_as_winansi():
    body = EXPORT_FORMATS["pdf"].render(make_report([expense(description="Café ☃")]))
    # e-acute is WinAnsi 0351 (octal); the snowman has no WinAnsi glyph and becomes '?'.
    assert r"(Caf\351 ?)" in pdf_text(body)


def test_font_metrics_tables_cover_printable_ascii():
    assert len(_HELVETICA_WIDTHS) == len(_HELVETICA_BOLD_WIDTHS) == 95
    assert text_width("0000", 10) == pytest.approx(22.24)


def test_fit_text_truncates_with_ellipsis():
    long = "A very long description that will not fit in the column"
    fitted = fit_text(long, 100, 9)
    assert fitted.endswith("…")
    assert text_width(fitted, 9) <= 100
    assert fit_text("Short", 100, 9) == "Short"


# ---------- Routes ----------


@pytest.fixture
def seeded(client):
    add(client, "Groceries", 50, "Food", "2026-09-10")
    add(client, "Electric bill", 120, "Bills", "2026-09-15")
    add(client, "Cinema", 18, "Entertainment", "2026-08-20")
    add(client, "Takeaway", 25, "Food", "2026-07-02")
    return client


def test_preview_applies_date_and_category_filters(seeded):
    resp = seeded.get("/export/preview?from=2026-08-01&to=2026-09-30&categories=Food,Entertainment")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["summary"]["count"] == 2
    assert data["summary"]["total"] == 68
    assert data["summary"]["total_display"] == "$68.00"
    assert [r["description"] for r in data["rows"]] == ["Groceries", "Cinema"]
    # Chip counts reflect the date range but ignore the category selection.
    assert data["category_counts"]["Bills"] == 1
    assert data["category_counts"]["Food"] == 1


def test_preview_limits_rows_but_counts_everything(client):
    for i in range(55):
        add(client, f"Item {i}", 1, "Other", "2026-09-01")
    data = client.get("/export/preview").get_json()
    assert data["summary"]["count"] == 55
    assert len(data["rows"]) == data["row_limit"] == 50


def test_preview_reports_validation_errors(seeded):
    resp = seeded.get("/export/preview?from=2026-09-30&to=2026-09-01&categories=")
    assert resp.status_code == 400
    assert set(resp.get_json()["errors"]) == {"to", "categories"}


def test_preview_resolves_filename(seeded):
    data = seeded.get("/export/preview?format=pdf&filename=My%20report.csv").get_json()
    assert data["filename"] == "My report.pdf"


@pytest.mark.parametrize(
    "fmt, mimetype, magic",
    [("csv", "text/csv", b"\xef\xbb\xbfDate,"), ("json", "application/json", b"{"), ("pdf", "application/pdf", b"%PDF")],
)
def test_download_each_format(seeded, fmt, mimetype, magic):
    resp = seeded.get(f"/export/download?format={fmt}&categories=Food&filename=food-spend")
    assert resp.status_code == 200
    assert resp.mimetype == mimetype
    assert resp.headers["Content-Disposition"] == f"attachment; filename=food-spend.{fmt}"
    assert resp.headers["X-Export-Record-Count"] == "2"
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.data.startswith(magic)


def test_download_respects_sort(seeded):
    body = seeded.get("/export/download?format=json&sort=amount-desc").get_json()
    assert [e["amount"] for e in body["expenses"]] == [120, 50, 25, 18]


def test_download_rejects_invalid_options(seeded):
    resp = seeded.get("/export/download?format=xlsx")
    assert resp.status_code == 400
    assert "format" in resp.get_json()["errors"]


def test_dashboard_has_export_dialog(seeded):
    html = seeded.get("/").get_data(as_text=True)
    assert "data-export-open" in html
    assert 'id="export-dialog"' in html
    assert "js/export.js" in html
    for fmt in ("csv", "json", "pdf"):
        assert f'value="{fmt}"' in html


def test_empty_dashboard_has_no_export(client):
    html = client.get("/").get_data(as_text=True)
    assert "export-dialog" not in html
