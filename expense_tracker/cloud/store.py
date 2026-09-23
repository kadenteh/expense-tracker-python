"""SQLite access for export jobs, share links, connected services and schedules."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..db import get_db
from .services import DESTINATIONS, INTEGRATIONS, Destination
from .templates import TEMPLATES, ExportTemplate

ACTIVE_STATUSES = ("queued", "running")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


# ---------- Jobs ----------

# Everything except the file bytes, which only the download route needs.
_JOB_COLUMNS = (
    "id, template, period, destination, options, trigger, status, progress, stage, title, "
    "filename, mimetype, size, checksum, record_count, preview, result, error, created_at, finished_at"
)


@dataclass
class Job:
    id: str
    template_key: str
    period: str
    destination_key: str
    options: dict
    trigger: str
    status: str
    progress: int
    stage: str
    title: str
    filename: Optional[str]
    mimetype: Optional[str]
    size: Optional[int]
    checksum: Optional[str]
    record_count: Optional[int]
    preview: Optional[dict]
    result: dict
    error: Optional[str]
    created_at: datetime
    finished_at: Optional[datetime]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            template_key=row["template"],
            period=row["period"],
            destination_key=row["destination"],
            options=json.loads(row["options"] or "{}"),
            trigger=row["trigger"],
            status=row["status"],
            progress=row["progress"],
            stage=row["stage"],
            title=row["title"],
            filename=row["filename"],
            mimetype=row["mimetype"],
            size=row["size"],
            checksum=row["checksum"],
            record_count=row["record_count"],
            preview=json.loads(row["preview"]) if row["preview"] else None,
            result=json.loads(row["result"] or "{}"),
            error=row["error"],
            created_at=parse_iso(row["created_at"]),
            finished_at=parse_iso(row["finished_at"]),
        )

    @property
    def template(self) -> Optional[ExportTemplate]:
        return TEMPLATES.get(self.template_key)

    @property
    def destination(self) -> Optional[Destination]:
        return DESTINATIONS.get(self.destination_key)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def duration_seconds(self) -> Optional[float]:
        if not self.finished_at:
            return None
        return (self.finished_at - self.created_at).total_seconds()


def insert_job(template: str, period: str, destination: str, options: dict, trigger: str, title: str) -> str:
    job_id = secrets.token_hex(6)
    db = get_db()
    db.execute(
        "INSERT INTO export_jobs (id, template, period, destination, options, trigger, status, stage, title, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'queued', 'Waiting in queue', ?, ?)",
        (job_id, template, period, destination, json.dumps(options), trigger, title, iso(now_utc())),
    )
    db.commit()
    return job_id


def update_job(job_id: str, **fields) -> None:
    for key in ("preview", "result"):
        if key in fields and not isinstance(fields[key], (str, type(None))):
            fields[key] = json.dumps(fields[key])
    assignments = ", ".join(f"{name} = ?" for name in fields)
    db = get_db()
    db.execute(f"UPDATE export_jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
    db.commit()


def get_job(job_id: str) -> Optional[Job]:
    row = get_db().execute(f"SELECT {_JOB_COLUMNS} FROM export_jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def get_job_file(job_id: str) -> Optional[sqlite3.Row]:
    return get_db().execute(
        "SELECT filename, mimetype, content FROM export_jobs WHERE id = ? AND status = 'done'", (job_id,)
    ).fetchone()


def list_jobs(limit: int = 25) -> list[Job]:
    rows = get_db().execute(
        f"SELECT {_JOB_COLUMNS} FROM export_jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
    ).fetchall()
    return [Job.from_row(r) for r in rows]


def delete_job(job_id: str) -> None:
    db = get_db()
    db.execute("DELETE FROM export_jobs WHERE id = ?", (job_id,))
    db.commit()


def active_job_count() -> int:
    return get_db().execute(
        "SELECT COUNT(*) FROM export_jobs WHERE status IN ('queued', 'running')"
    ).fetchone()[0]


def has_active_job(destination: str) -> bool:
    return bool(
        get_db().execute(
            "SELECT 1 FROM export_jobs WHERE destination = ? AND status IN ('queued', 'running') LIMIT 1",
            (destination,),
        ).fetchone()
    )


def fail_orphaned_jobs() -> None:
    """Jobs left queued/running by a previous server process will never finish."""
    db = get_db()
    db.execute(
        "UPDATE export_jobs SET status = 'failed', error = 'Interrupted by a server restart', finished_at = ? "
        "WHERE status IN ('queued', 'running')",
        (iso(now_utc()),),
    )
    db.commit()


# ---------- Share links ----------


@dataclass
class ShareLink:
    token: str
    job_id: str
    redact: bool
    created_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    views: int
    last_viewed_at: Optional[datetime]
    job_title: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ShareLink":
        keys = row.keys()
        return cls(
            token=row["token"],
            job_id=row["job_id"],
            redact=bool(row["redact"]),
            created_at=parse_iso(row["created_at"]),
            expires_at=parse_iso(row["expires_at"]),
            revoked_at=parse_iso(row["revoked_at"]),
            views=row["views"],
            last_viewed_at=parse_iso(row["last_viewed_at"]),
            job_title=row["title"] if "title" in keys else "",
        )

    @property
    def status(self) -> str:
        if self.revoked_at:
            return "revoked"
        if self.expires_at and self.expires_at <= now_utc():
            return "expired"
        return "active"

    @property
    def is_active(self) -> bool:
        return self.status == "active"


def create_share(job_id: str, expiry: str, redact: bool) -> ShareLink:
    token = secrets.token_urlsafe(9)
    created = now_utc()
    expires = None if expiry == "never" else created + timedelta(days=int(expiry))
    db = get_db()
    db.execute(
        "INSERT INTO share_links (token, job_id, redact, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (token, job_id, int(redact), iso(created), iso(expires) if expires else None),
    )
    db.commit()
    return get_share(token)


def get_share(token: str) -> Optional[ShareLink]:
    row = get_db().execute(
        "SELECT s.*, j.title FROM share_links s JOIN export_jobs j ON j.id = s.job_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    return ShareLink.from_row(row) if row else None


def list_shares(limit: int = 20) -> list[ShareLink]:
    rows = get_db().execute(
        "SELECT s.*, j.title FROM share_links s JOIN export_jobs j ON j.id = s.job_id "
        "WHERE s.revoked_at IS NULL ORDER BY s.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [ShareLink.from_row(r) for r in rows]


def revoke_share(token: str) -> None:
    db = get_db()
    db.execute("UPDATE share_links SET revoked_at = ? WHERE token = ?", (iso(now_utc()), token))
    db.commit()


def record_share_view(token: str) -> None:
    db = get_db()
    db.execute(
        "UPDATE share_links SET views = views + 1, last_viewed_at = ? WHERE token = ?", (iso(now_utc()), token)
    )
    db.commit()


# ---------- Connected services ----------


def connected_services() -> dict[str, sqlite3.Row]:
    rows = get_db().execute("SELECT * FROM integrations").fetchall()
    return {r["key"]: r for r in rows if r["key"] in INTEGRATIONS}


def is_connected(key: str) -> bool:
    return bool(get_db().execute("SELECT 1 FROM integrations WHERE key = ?", (key,)).fetchone())


def connect_service(key: str) -> None:
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO integrations (key, account, connected_at) VALUES (?, ?, ?)",
        (key, INTEGRATIONS[key].demo_account, iso(now_utc())),
    )
    db.commit()


def disconnect_service(key: str) -> None:
    db = get_db()
    db.execute("DELETE FROM integrations WHERE key = ?", (key,))
    db.commit()


def set_auto_sync(key: str, enabled: bool) -> None:
    db = get_db()
    db.execute("UPDATE integrations SET auto_sync = ? WHERE key = ?", (int(enabled), key))
    db.commit()


def mark_synced(key: str, fingerprint: str, synced_at: datetime) -> None:
    """`synced_at` is when `fingerprint` was taken, at full precision, so
    count_added_since() can tell apart expenses added in the same second."""
    db = get_db()
    db.execute(
        "UPDATE integrations SET last_sync_at = ?, last_sync_fingerprint = ? WHERE key = ?",
        (synced_at.isoformat(), fingerprint, key),
    )
    db.commit()


# ---------- Change detection ----------


def expenses_fingerprint() -> str:
    """A hash of every expense, so any add, edit or delete changes it."""
    digest = hashlib.sha256()
    for row in get_db().execute(
        "SELECT id, description, amount, category, date FROM expenses ORDER BY id"
    ):
        digest.update("|".join(str(v) for v in row).encode("utf-8") + b"\n")
    return digest.hexdigest()


def count_added_since(moment: datetime) -> int:
    return get_db().execute(
        "SELECT COUNT(*) FROM expenses WHERE julianday(created_at) > julianday(?)", (moment.isoformat(),)
    ).fetchone()[0]


# ---------- Schedules ----------


@dataclass
class Schedule:
    id: int
    template_key: str
    destination_key: str
    frequency: str
    options: dict
    enabled: bool
    next_run_at: datetime
    last_run_at: Optional[datetime]
    created_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Schedule":
        return cls(
            id=row["id"],
            template_key=row["template"],
            destination_key=row["destination"],
            frequency=row["frequency"],
            options=json.loads(row["options"] or "{}"),
            enabled=bool(row["enabled"]),
            next_run_at=parse_iso(row["next_run_at"]),
            last_run_at=parse_iso(row["last_run_at"]),
            created_at=parse_iso(row["created_at"]),
        )

    @property
    def template(self) -> Optional[ExportTemplate]:
        return TEMPLATES.get(self.template_key)

    @property
    def destination(self) -> Optional[Destination]:
        return DESTINATIONS.get(self.destination_key)


def create_schedule(template: str, destination: str, frequency: str, options: dict, next_run: datetime) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO schedules (template, destination, frequency, options, next_run_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (template, destination, frequency, json.dumps(options), iso(next_run), iso(now_utc())),
    )
    db.commit()
    return cur.lastrowid


def get_schedule(schedule_id: int) -> Optional[Schedule]:
    row = get_db().execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    return Schedule.from_row(row) if row else None


def list_schedules() -> list[Schedule]:
    rows = get_db().execute("SELECT * FROM schedules ORDER BY created_at DESC, id DESC").fetchall()
    return [Schedule.from_row(r) for r in rows]


def due_schedules(moment: datetime) -> list[Schedule]:
    rows = get_db().execute(
        "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ?", (iso(moment),)
    ).fetchall()
    return [Schedule.from_row(r) for r in rows]


def update_schedule(schedule_id: int, **fields) -> None:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = [iso(v) if isinstance(v, datetime) else v for v in fields.values()]
    db = get_db()
    db.execute(f"UPDATE schedules SET {assignments} WHERE id = ?", (*values, schedule_id))
    db.commit()


def delete_schedule(schedule_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    db.commit()
