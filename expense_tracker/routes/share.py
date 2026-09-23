"""Public, read-only pages for share links (no app navigation)."""

from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, abort, render_template, send_file

from ..cloud import store
from ..formatting import format_local, format_relative

bp = Blueprint("share", __name__, url_prefix="/s")

HIDDEN = "[hidden]"


def _active_link_and_job(token: str):
    link = store.get_share(token)
    if not link:
        abort(404)
    job = store.get_job(link.job_id)
    if not link.is_active or not job:
        return link, None
    return link, job


def _visible_rows(link: store.ShareLink, job: store.Job) -> list[list[str]]:
    preview = job.preview or {}
    column = preview.get("sensitive_column")
    rows = preview.get("rows", [])
    if not (link.redact and column is not None):
        return rows
    return [[HIDDEN if i == column else cell for i, cell in enumerate(row)] for row in rows]


@bp.get("/<token>")
def view(token: str):
    link, job = _active_link_and_job(token)
    if job is None:
        return render_template("share/unavailable.html", link=link), 410
    store.record_share_view(token)
    return render_template(
        "share/view.html",
        link=link,
        job=job,
        rows=_visible_rows(link, job),
        expires_label=("Expires " + format_relative(link.expires_at)) if link.expires_at else "No expiry",
        expires_at=format_local(link.expires_at),
        hidden=HIDDEN,
    )


@bp.get("/<token>/download")
def download(token: str):
    link, job = _active_link_and_job(token)
    if job is None:
        abort(410)
    if not link.redact:
        row = store.get_job_file(job.id)
        return send_file(
            io.BytesIO(row["content"]), mimetype=row["mimetype"], as_attachment=True, download_name=row["filename"]
        )

    # Redacted links never hand out the original file, only the masked table.
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(job.preview["headers"])
    writer.writerows(_visible_rows(link, job))
    stem = (job.filename or "export").rsplit(".", 1)[0]
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={stem}-shared.csv"},
    )
