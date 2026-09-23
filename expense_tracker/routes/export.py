from __future__ import annotations

from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from ..exports import EXPORT_FORMATS, build_report, default_filename_stem, parse_export_options
from ..formatting import format_currency, format_date
from ..models import Expense, SORT_OPTIONS, count_by_category

bp = Blueprint("export", __name__, url_prefix="/export")

PREVIEW_ROW_LIMIT = 50

SORT_LABELS = {
    "date-desc": "Newest first",
    "date-asc": "Oldest first",
    "amount-desc": "Highest amount",
    "amount-asc": "Lowest amount",
}
assert SORT_LABELS.keys() == SORT_OPTIONS.keys()


@bp.app_context_processor
def inject_export_choices():
    return {"EXPORT_FORMATS": list(EXPORT_FORMATS.values()), "EXPORT_SORT_LABELS": SORT_LABELS}


def _row_json(e: Expense) -> dict:
    return {
        "id": e.id,
        "date": e.date,
        "date_display": format_date(e.date),
        "category": e.category,
        "amount": round(e.amount, 2),
        "amount_display": format_currency(e.amount),
        "description": e.description,
    }


@bp.get("/preview")
def preview():
    options, errors = parse_export_options(request.args, EXPORT_FORMATS)
    if errors:
        return jsonify(errors=errors), 400

    report = build_report(options)
    fmt = EXPORT_FORMATS[options.format]
    return jsonify(
        summary={
            "count": report.count,
            "total": report.total,
            "total_display": format_currency(report.total),
            "period": report.period_label,
            "categories": report.categories_label,
        },
        rows=[_row_json(e) for e in report.expenses[:PREVIEW_ROW_LIMIT]],
        row_limit=PREVIEW_ROW_LIMIT,
        category_counts=count_by_category(options.date_from, options.date_to),
        filename=options.filename_for(fmt.extension),
        default_stem=default_filename_stem(),
    )


@bp.get("/download")
def download():
    options, errors = parse_export_options(request.args, EXPORT_FORMATS)
    if errors:
        return jsonify(errors=errors), 400

    report = build_report(options)
    fmt = EXPORT_FORMATS[options.format]
    response = send_file(
        BytesIO(fmt.render(report)),
        mimetype=fmt.mimetype,
        as_attachment=True,
        download_name=options.filename_for(fmt.extension),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Export-Record-Count"] = str(report.count)
    return response
