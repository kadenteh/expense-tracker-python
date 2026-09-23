"""The export pipeline: validates requests, runs jobs in the background, and
drives recurring schedules and live sync.

Jobs run on a worker thread so the UI stays responsive and can show progress.
Simulated destinations sleep between stages (scaled by the
EXPORT_SIMULATED_LATENCY config value) so the background processing is visible.
"""

from __future__ import annotations

import calendar
import hashlib
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import Flask, current_app

from . import store
from .services import DESTINATIONS, FREQUENCIES, INTEGRATIONS, SHARE_EXPIRY_OPTIONS
from .templates import TEMPLATES, ExportArtifact

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_RECIPIENTS = 10
TICK_INTERVAL_SECONDS = 20


class ExportRequestError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


# ---------- Validation ----------


def validate_request(template: str, period: str, destination: str, options: dict) -> dict:
    """Checks a new-export request. Returns the cleaned destination options."""
    errors: dict[str, str] = {}
    tpl = TEMPLATES.get(template)
    if not tpl:
        errors["template"] = "Choose a template."
    elif period not in dict(tpl.periods()):
        errors["period"] = "Choose a period for this template."

    dest = DESTINATIONS.get(destination)
    clean: dict = {}
    if not dest:
        errors["destination"] = "Choose where to send the export."
    else:
        if dest.integration and not store.is_connected(dest.integration):
            errors["destination"] = f"Connect {INTEGRATIONS[dest.integration].name} first."
        if destination == "email":
            clean, email_errors = _clean_email_options(options)
            errors.update(email_errors)
        elif destination == "share":
            clean = _clean_share_options(options, errors)

    if errors:
        raise ExportRequestError(errors)
    return clean


def _clean_email_options(options: dict) -> tuple[dict, dict]:
    errors = {}
    raw = options.get("recipients", "")
    recipients = [r.strip() for r in re.split(r"[,;\s]+", raw) if r.strip()]
    invalid = [r for r in recipients if not EMAIL_PATTERN.match(r)]
    if not recipients:
        errors["recipients"] = "Add at least one recipient."
    elif invalid:
        errors["recipients"] = "Check these addresses: " + ", ".join(invalid[:3])
    elif len(recipients) > MAX_RECIPIENTS:
        errors["recipients"] = f"Send to at most {MAX_RECIPIENTS} people at once."
    subject = (options.get("subject") or "").strip()[:150]
    message = (options.get("message") or "").strip()[:2000]
    return {"recipients": recipients, "subject": subject, "message": message}, errors


def _clean_share_options(options: dict, errors: dict) -> dict:
    expiry = str(options.get("expiry", "7"))
    if expiry not in SHARE_EXPIRY_OPTIONS:
        errors["expiry"] = "Choose when the link expires."
    return {"expiry": expiry, "redact": bool(options.get("redact"))}


# ---------- Starting jobs ----------


def start_job(
    template: str, period: str, destination: str, options: Optional[dict] = None, trigger: str = "manual"
) -> str:
    clean = validate_request(template, period, destination, options or {})
    tpl = TEMPLATES[template]
    title = f"{tpl.name} · {tpl.period_label(period)}"
    job_id = store.insert_job(template, period, destination, clean, trigger, title)
    _dispatch(job_id)
    return job_id


def rerun_job(job_id: str) -> str:
    job = store.get_job(job_id)
    if not job:
        raise ExportRequestError({"job": "That export no longer exists."})
    options = dict(job.options)
    if job.destination_key == "email":
        options["recipients"] = ", ".join(options.get("recipients", []))
    return start_job(job.template_key, job.period, job.destination_key, options, trigger="rerun")


def _dispatch(job_id: str) -> None:
    app = current_app._get_current_object()
    if app.config.get("EXPORT_JOBS_INLINE"):
        run_job(app, job_id)
    else:
        threading.Thread(target=run_job, args=(app, job_id), name=f"export-{job_id}", daemon=True).start()


# ---------- Running jobs ----------


def _destination_stages(destination: str, artifact: ExportArtifact, options: dict) -> list[tuple[str, float]]:
    rows = f"{len(artifact.rows):,} row{'s' if len(artifact.rows) != 1 else ''}"
    return {
        "download": [("Preparing download", 0.2)],
        "share": [("Generating secure token", 0.3), ("Publishing share page", 0.4)],
        "email": [
            ("Rendering email", 0.5),
            (f"Sending to {len(options.get('recipients', []))} recipient(s)", 0.9),
        ],
        "google-sheets": [
            ("Connecting to Google Sheets", 0.6),
            (f"Writing {rows}", 1.0),
            ("Applying formatting", 0.5),
        ],
        "dropbox": [("Connecting to Dropbox", 0.5), (f"Uploading {artifact.filename}", 1.0), ("Verifying checksum", 0.4)],
        "onedrive": [("Connecting to OneDrive", 0.5), (f"Uploading {artifact.filename}", 1.0), ("Verifying checksum", 0.4)],
        "slack": [("Composing summary", 0.4), ("Posting to #finance", 0.7)],
    }[destination]


def _deliver(destination: str, job: store.Job, artifact: ExportArtifact) -> dict:
    """What the destination did with the file. Only 'share' has a real side effect."""
    if destination == "share":
        link = store.create_share(job.id, job.options["expiry"], job.options["redact"])
        return {"token": link.token}
    if destination == "email":
        return {
            "recipients": job.options["recipients"],
            "subject": job.options["subject"] or artifact.title,
            "message": job.options["message"],
        }
    if destination == "google-sheets":
        return {"location": f"My Drive › Expense Tracker › {artifact.title}", "rows": len(artifact.rows)}
    if destination == "dropbox":
        return {"location": f"/Apps/Expense Tracker/{artifact.filename}"}
    if destination == "onedrive":
        return {"location": f"Documents › Expense Tracker › {artifact.filename}"}
    if destination == "slack":
        facts = " · ".join(f"{label}: {value}" for label, value in artifact.highlights)
        return {"channel": "#finance", "text": f"*{artifact.title}*\n{facts}"}
    return {}


def run_job(app: Flask, job_id: str) -> None:
    with app.app_context():
        latency = float(app.config.get("EXPORT_SIMULATED_LATENCY", 1.0))
        job = store.get_job(job_id)
        if not job:
            return

        def step(progress: int, stage: str, seconds: float = 0.0) -> None:
            store.update_job(job_id, status="running", progress=progress, stage=stage)
            if seconds and latency:
                time.sleep(seconds * latency)

        try:
            step(8, "Collecting expenses", 0.4)
            artifact = job.template.build(job.period)
            step(30, f"Generating {job.template.name}", 0.5)
            store.update_job(
                job_id,
                title=artifact.title,
                filename=artifact.filename,
                mimetype=artifact.mimetype,
                content=artifact.content,
                size=len(artifact.content),
                checksum=hashlib.sha256(artifact.content).hexdigest(),
                record_count=artifact.record_count,
                preview=artifact.preview(),
            )

            integration = job.destination.integration
            stages = _destination_stages(job.destination_key, artifact, job.options)
            for index, (label, seconds) in enumerate(stages):
                if integration and not store.is_connected(integration):
                    raise RuntimeError(f"{INTEGRATIONS[integration].name} was disconnected")
                step(35 + int(60 * index / len(stages)), label, seconds)

            synced_at = datetime.now(timezone.utc)
            fingerprint = store.expenses_fingerprint()
            result = _deliver(job.destination_key, job, artifact)
            store.update_job(
                job_id, status="done", progress=100, stage="Complete", result=result,
                finished_at=store.iso(store.now_utc()),
            )
            if integration:
                store.mark_synced(integration, fingerprint, synced_at)
        except Exception as exc:  # the job record is the error report
            store.update_job(
                job_id, status="failed", stage="Failed", error=str(exc) or exc.__class__.__name__,
                finished_at=store.iso(store.now_utc()),
            )


# ---------- Schedules ----------


def next_run_after(frequency: str, moment: datetime) -> datetime:
    if frequency == "daily":
        return moment + timedelta(days=1)
    if frequency == "weekly":
        return moment + timedelta(weeks=1)
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def create_schedule(template: str, destination: str, frequency: str, options: dict) -> int:
    errors = {}
    if frequency not in FREQUENCIES:
        errors["frequency"] = "Choose how often to run."
    if destination == "share":
        errors["destination"] = "Share links can't be scheduled. Pick a delivery destination."
    try:
        tpl = TEMPLATES.get(template)
        clean = validate_request(template, tpl.scheduled_period() if tpl else "", destination, options)
    except ExportRequestError as exc:
        errors = {**exc.errors, **errors}
    if errors:
        raise ExportRequestError(errors)
    return store.create_schedule(template, destination, frequency, clean, next_run_after(frequency, store.now_utc()))


def run_schedule(schedule: store.Schedule, trigger: str = "schedule") -> Optional[str]:
    """Starts one run. A run that can't start (e.g. service disconnected) is logged as failed."""
    tpl = schedule.template
    options = dict(schedule.options)
    if schedule.destination_key == "email":
        options["recipients"] = ", ".join(options.get("recipients", []))
    try:
        job_id = start_job(schedule.template_key, tpl.scheduled_period(), schedule.destination_key, options, trigger)
    except ExportRequestError as exc:
        job_id = store.insert_job(
            schedule.template_key, tpl.scheduled_period(), schedule.destination_key, schedule.options,
            trigger, f"{tpl.name} · {tpl.period_label(tpl.scheduled_period())}",
        )
        store.update_job(
            job_id, status="failed", stage="Failed", error=str(exc), finished_at=store.iso(store.now_utc())
        )
    store.update_schedule(schedule.id, last_run_at=store.now_utc())
    return job_id


def run_due_schedules(moment: Optional[datetime] = None) -> list[str]:
    moment = moment or store.now_utc()
    started = []
    for schedule in store.due_schedules(moment):
        # Advance first, so a slow or failing run can never be picked up twice.
        # Missed runs are caught up once, not replayed one by one.
        next_run = schedule.next_run_at
        while next_run <= moment:
            next_run = next_run_after(schedule.frequency, next_run)
        store.update_schedule(schedule.id, next_run_at=next_run)
        started.append(run_schedule(schedule))
    return started


# ---------- Live sync ----------


def sync_state(key: str, row, fingerprint: str) -> dict:
    """Human-facing sync status for one connected service."""
    if store.has_active_job(key):
        return {"state": "syncing", "label": "Syncing…"}
    if not INTEGRATIONS[key].live_sync:
        return {"state": "ready", "label": "Connected"}
    if not row["last_sync_at"]:
        return {"state": "idle", "label": "Not synced yet"}
    if row["last_sync_fingerprint"] == fingerprint:
        return {"state": "synced", "label": "Up to date"}
    added = store.count_added_since(store.parse_iso(row["last_sync_at"]))
    label = f"{added} new expense{'s' if added != 1 else ''} since last sync" if added else "Edited since last sync"
    return {"state": "stale", "label": label}


def run_live_sync() -> list[str]:
    """Mirrors data to every live-sync service whose copy is out of date."""
    fingerprint = store.expenses_fingerprint()
    started = []
    for key, row in store.connected_services().items():
        if not (row["auto_sync"] and INTEGRATIONS[key].live_sync):
            continue
        if row["last_sync_fingerprint"] == fingerprint or store.has_active_job(key):
            continue
        started.append(start_job("full-backup", "all", key, trigger="auto-sync"))
    return started


def tick(force: bool = False) -> None:
    """Runs due schedules and live sync, at most every TICK_INTERVAL_SECONDS.

    There's no separate scheduler process: work is picked up while the app is
    in use, and anything missed while it was closed runs on the next visit.
    """
    state = current_app.extensions.setdefault("export_center", {"last_tick": 0.0})
    now = time.monotonic()
    if not force and now - state["last_tick"] < TICK_INTERVAL_SECONDS:
        return
    state["last_tick"] = now
    run_due_schedules()
    run_live_sync()


def format_size(size: Optional[int]) -> str:
    if size is None:
        return "—"
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""

