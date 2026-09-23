from __future__ import annotations

from io import BytesIO

from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from ..cloud import jobs, store
from ..cloud.qr import qr_svg
from ..cloud.services import DESTINATIONS, FREQUENCIES, INTEGRATIONS, SHARE_EXPIRY_OPTIONS
from ..cloud.templates import TEMPLATES
from ..exports import ALL_FORMATS
from ..formatting import format_local, format_relative

bp = Blueprint("exports", __name__, url_prefix="/exports")

# Sent by export-center.js on every API call. A cross-site form or link can't
# set a custom header, and a cross-site script would need a CORS preflight that
# this app never approves, so requiring it blocks CSRF on the JSON API.
API_HEADER = "X-Requested-With"
API_HEADER_VALUE = "ExportCenter"


@bp.before_request
def protect_api():
    if request.method in ("GET", "HEAD", "OPTIONS") or not request.path.startswith("/exports/api/"):
        return None
    if request.headers.get(API_HEADER) != API_HEADER_VALUE:
        return jsonify(errors={"request": "Missing API header."}), 403
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return jsonify(errors={"request": "Cross-origin request refused."}), 403
    return None


@bp.app_context_processor
def inject_export_status():
    return {"active_export_count": store.active_job_count()}


@bp.before_app_request
def background_tick():
    """Picks up due schedules and live sync while the app is being used."""
    if request.method == "GET" and request.endpoint != "static" and not current_app.config.get("TESTING"):
        jobs.tick()


@bp.after_app_request
def live_sync_after_edit(response):
    """Mirror to live-sync services as soon as an expense is added, edited or deleted."""
    if (
        request.method == "POST"
        and request.blueprint == "expenses"
        and response.status_code == 302  # the success redirect, not a re-rendered form
        and not current_app.config.get("TESTING")
    ):
        jobs.run_live_sync()
    return response


# ---------- Page and live panels ----------


def _share_url(token: str) -> str:
    return url_for("share.view", token=token, _external=True)


def _panel_context() -> dict:
    version = store.data_version()
    connected = store.connected_services()
    services = [
        {
            "integration": integration,
            "row": connected.get(key),
            "sync": jobs.sync_state(key, connected[key], version) if key in connected else None,
            "last_sync": store.parse_iso(connected[key]["last_sync_at"]) if key in connected else None,
        }
        for key, integration in INTEGRATIONS.items()
    ]
    job_list = store.list_jobs()
    active = [j for j in job_list if j.is_active]
    stale = [s for s in services if s["sync"] and s["sync"]["state"] == "stale"]
    return {
        "jobs": job_list,
        "active_jobs": active,
        "services": services,
        "connected_keys": list(connected),
        "stale_services": stale,
        "schedules": store.list_schedules(),
        "shares": store.list_shares(),
        "share_url": _share_url,
        "format_size": jobs.format_size,
        "integrations_catalog": INTEGRATIONS,
        "frequencies": FREQUENCIES,
        "formats": ALL_FORMATS,
    }


PANELS = {
    "status": "exports/_status.html",
    "activity": "exports/_activity.html",
    "services": "exports/_services.html",
    "schedules": "exports/_schedules.html",
    "shares": "exports/_shares.html",
}


def _client_data(connected_keys: list[str]) -> dict:
    """Catalog data the page script needs to drive the new-export drawer."""
    return {
        "templates": {
            key: {
                "name": t.name,
                "periods": t.periods(),
                "default_period": t.default_period(),
                "scheduled_period": t.period_label(t.scheduled_period()),
                "formats": [[f, ALL_FORMATS[f].label, ALL_FORMATS[f].tabular] for f in t.formats],
            }
            for key, t in TEMPLATES.items()
        },
        "destinations": {
            key: {"name": d.name, "integration": d.integration, "simulated": d.simulated}
            for key, d in DESTINATIONS.items()
        },
        "integrations": {
            key: {
                "name": i.name,
                "monogram": i.monogram,
                "color": i.color,
                "scopes": list(i.scopes),
                "account": i.demo_account,
            }
            for key, i in INTEGRATIONS.items()
        },
        "frequencies": FREQUENCIES,
        "connected": connected_keys,
        "api_header": [API_HEADER, API_HEADER_VALUE],
        "urls": {
            "panels": url_for("exports.panels"),
            "jobs": url_for("exports.create_job"),
            "schedules": url_for("exports.create_schedule"),
            "api": url_for("exports.center") + "api",
        },
    }


@bp.get("/")
def center():
    jobs.tick()
    context = _panel_context()
    return render_template(
        "exports/center.html",
        templates=TEMPLATES,
        destinations=DESTINATIONS,
        integrations=INTEGRATIONS,
        expiry_options=SHARE_EXPIRY_OPTIONS,
        client_data=_client_data(context["connected_keys"]),
        **context,
    )


@bp.get("/panels")
def panels():
    jobs.tick()
    context = _panel_context()
    return jsonify(
        panels={name: render_template(tpl, **context) for name, tpl in PANELS.items()},
        jobs=[
            {
                "id": j.id,
                "status": j.status,
                "title": j.title,
                "destination": j.destination.name if j.destination else j.destination_key,
                "destination_key": j.destination_key,
                "error": j.error,
            }
            for j in context["jobs"]
        ],
        connected=context["connected_keys"],
        active=len(context["active_jobs"]),
    )


# ---------- Jobs ----------


def _error_response(exc: jobs.ExportRequestError):
    return jsonify(errors=exc.errors), 400


@bp.post("/api/jobs")
def create_job():
    body = request.get_json(silent=True) or {}
    try:
        job_id = jobs.start_job(
            body.get("template", ""),
            body.get("period", ""),
            body.get("destination", ""),
            body.get("options") or {},
            fmt=body.get("format", ""),
        )
    except jobs.ExportRequestError as exc:
        return _error_response(exc)
    return jsonify(id=job_id), 201


@bp.post("/api/jobs/<job_id>/rerun")
def rerun(job_id: str):
    try:
        return jsonify(id=jobs.rerun_job(job_id)), 201
    except jobs.ExportRequestError as exc:
        return _error_response(exc)


@bp.delete("/api/jobs/<job_id>")
def delete(job_id: str):
    job = store.get_job(job_id)
    if job and job.is_active:
        return jsonify(errors={"job": "Wait for the export to finish before deleting it."}), 409
    store.delete_job(job_id)
    return jsonify(ok=True)


@bp.get("/jobs/<job_id>/download")
def download(job_id: str):
    row = store.get_job_file(job_id)
    if not row:
        job = store.get_job(job_id)
        if job and job.file_removed_at:
            return "This export's file was removed by the retention policy. Run it again to get a fresh copy.", 410
        abort(404)
    return send_file(
        BytesIO(row["content"]), mimetype=row["mimetype"], as_attachment=True, download_name=row["filename"]
    )


@bp.get("/jobs/<job_id>/preview")
def preview(job_id: str):
    job = store.get_job(job_id)
    if not job or job.status != "done":
        abort(404)
    return render_template(
        "exports/preview.html", job=job, integrations=INTEGRATIONS, format_size=jobs.format_size
    )


# ---------- Sharing ----------


def _share_payload(link: store.ShareLink) -> dict:
    url = _share_url(link.token)
    return {
        "token": link.token,
        "url": url,
        "qr_svg": qr_svg(url),
        "title": link.job_title,
        "redact": link.redact,
        "status": link.status,
        "views": link.views,
        "expires": ("Expires " + format_relative(link.expires_at)) if link.expires_at else "Never expires",
        "expires_at": format_local(link.expires_at),
    }


@bp.post("/api/jobs/<job_id>/share")
def share_job(job_id: str):
    job = store.get_job(job_id)
    if not job or not job.has_file:
        return jsonify(errors={"job": "Only finished exports that still have their file can be shared."}), 400
    body = request.get_json(silent=True) or {}
    expiry = str(body.get("expiry", "7"))
    if expiry not in SHARE_EXPIRY_OPTIONS:
        return jsonify(errors={"expiry": "Choose when the link expires."}), 400
    link = store.create_share(job_id, expiry, bool(body.get("redact")))
    return jsonify(_share_payload(link)), 201


@bp.get("/api/shares/<token>")
def share_details(token: str):
    link = store.get_share(token)
    if not link:
        abort(404)
    return jsonify(_share_payload(link))


@bp.get("/api/jobs/<job_id>/share")
def job_share_details(job_id: str):
    """The link a 'Share link' export created, so the UI can pop it open when the job finishes."""
    job = store.get_job(job_id)
    token = job.result.get("token") if job else None
    link = store.get_share(token) if token else None
    if not link:
        abort(404)
    return jsonify(_share_payload(link))


@bp.post("/api/shares/<token>/revoke")
def revoke_share(token: str):
    store.revoke_share(token)
    return jsonify(ok=True)


# ---------- Connected services ----------


def _integration_or_404(key: str):
    if key not in INTEGRATIONS:
        abort(404)
    return INTEGRATIONS[key]


@bp.post("/api/integrations/<key>/connect")
def connect(key: str):
    integration = _integration_or_404(key)
    store.connect_service(key)
    return jsonify(ok=True, account=integration.demo_account)


@bp.post("/api/integrations/<key>/disconnect")
def disconnect(key: str):
    _integration_or_404(key)
    store.disconnect_service(key)
    return jsonify(ok=True)


@bp.post("/api/integrations/<key>/auto-sync")
def auto_sync(key: str):
    integration = _integration_or_404(key)
    if not integration.live_sync or not store.is_connected(key):
        return jsonify(errors={"integration": f"{integration.name} can't live-sync."}), 400
    enabled = bool((request.get_json(silent=True) or {}).get("enabled"))
    store.set_auto_sync(key, enabled)
    if enabled:
        jobs.run_live_sync()
    return jsonify(ok=True)


@bp.post("/api/integrations/<key>/sync")
def sync_now(key: str):
    _integration_or_404(key)
    try:
        return jsonify(id=jobs.start_job("full-backup", "all", key)), 201
    except jobs.ExportRequestError as exc:
        return _error_response(exc)


# ---------- Schedules ----------


@bp.post("/api/schedules")
def create_schedule():
    body = request.get_json(silent=True) or {}
    try:
        schedule_id = jobs.create_schedule(
            body.get("template", ""),
            body.get("destination", ""),
            body.get("frequency", ""),
            body.get("options") or {},
            fmt=body.get("format", ""),
        )
    except jobs.ExportRequestError as exc:
        return _error_response(exc)
    return jsonify(id=schedule_id), 201


def _schedule_or_404(schedule_id: int) -> store.Schedule:
    schedule = store.get_schedule(schedule_id)
    if not schedule:
        abort(404)
    return schedule


@bp.post("/api/schedules/<int:schedule_id>/toggle")
def toggle_schedule(schedule_id: int):
    schedule = _schedule_or_404(schedule_id)
    fields = {"enabled": int(not schedule.enabled)}
    if not schedule.enabled and schedule.next_run_at <= store.now_utc():
        # Re-enabling shouldn't fire a backlog immediately.
        fields["next_run_at"] = jobs.next_run_after(schedule.frequency, store.now_utc())
    store.update_schedule(schedule_id, **fields)
    return jsonify(ok=True)


@bp.post("/api/schedules/<int:schedule_id>/run")
def run_schedule_now(schedule_id: int):
    return jsonify(id=jobs.run_schedule(_schedule_or_404(schedule_id), trigger="manual")), 201


@bp.delete("/api/schedules/<int:schedule_id>")
def delete_schedule(schedule_id: int):
    store.delete_schedule(schedule_id)
    return jsonify(ok=True)
