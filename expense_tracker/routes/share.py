"""Public, read-only pages for share links (no app navigation)."""

from __future__ import annotations

import io
import re

from flask import Blueprint, abort, make_response, render_template, request, send_file

from ..cloud import jobs, store
from ..exports import ReportTable
from ..exports.report import HIDDEN
from ..formatting import format_local, format_relative

bp = Blueprint("share", __name__, url_prefix="/s")

SHARE_PAGE_ROWS = 500
VIEWED_COOKIE_DAYS = 30

# Link unfurlers and crawlers fetch pages people haven't opened; don't count them.
_BOT_AGENTS = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|whatsapp|skypeuripreview|"
    r"linkedinbot|discordbot|telegrambot|slackbot|twitterbot|vkshare|iframely|headless",
    re.IGNORECASE,
)


def _active_link_and_job(token: str):
    link = store.get_share(token)
    if not link:
        abort(404)
    job = store.get_job(link.job_id)
    if not link.is_active or not job:
        return link, None
    return link, job


def _is_human_first_visit(token: str) -> bool:
    agent = request.headers.get("User-Agent", "")
    return not _BOT_AGENTS.search(agent) and request.cookies.get(f"seen_{token}") is None


@bp.get("/<token>")
def view(token: str):
    link, job = _active_link_and_job(token)
    if job is None:
        return render_template("share/unavailable.html", link=link), 410

    counted = _is_human_first_visit(token)
    if counted:
        store.record_share_view(token)

    table = ReportTable.from_dict(job.preview)
    if link.redact:
        table = table.redacted()
    response = make_response(
        render_template(
            "share/view.html",
            link=link,
            job=job,
            table=table,
            rows=table.rows[:SHARE_PAGE_ROWS],
            can_download=job.has_file,
            expires_label=("Expires " + format_relative(link.expires_at)) if link.expires_at else "No expiry",
            expires_at=format_local(link.expires_at),
            hidden=HIDDEN,
        )
    )
    if counted:
        response.set_cookie(
            f"seen_{token}", "1", max_age=VIEWED_COOKIE_DAYS * 86400, path=f"/s/{token}", httponly=True, samesite="Lax"
        )
    return response


@bp.get("/<token>/download")
def download(token: str):
    link, job = _active_link_and_job(token)
    if job is None:
        abort(410)

    if link.redact:
        # Re-rendered from the export's own snapshot: complete, same format,
        # descriptions hidden. The original file is never served.
        variant = jobs.render_job_variant(job, redact=True)
        if variant is None:
            abort(410)
        content, filename, mimetype = variant
    else:
        row = store.get_job_file(job.id)
        if row is None:
            abort(410)
        content, filename, mimetype = row["content"], row["filename"], row["mimetype"]

    return send_file(io.BytesIO(content), mimetype=mimetype, as_attachment=True, download_name=filename)
