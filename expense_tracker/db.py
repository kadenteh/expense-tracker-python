import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (date);

-- Export Center ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS export_jobs (
    id TEXT PRIMARY KEY,
    template TEXT NOT NULL,
    period TEXT NOT NULL,
    destination TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',   -- JSON: destination settings (recipients, expiry...)
    trigger TEXT NOT NULL DEFAULT 'manual', -- manual | schedule | auto-sync | rerun
    status TEXT NOT NULL,                 -- queued | running | done | failed
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    filename TEXT,
    mimetype TEXT,
    size INTEGER,
    checksum TEXT,
    record_count INTEGER,
    content BLOB,
    preview TEXT,                         -- JSON: table + highlights for previews and share pages
    result TEXT,                          -- JSON: what the destination did with it
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_export_jobs_created ON export_jobs (created_at);

CREATE TABLE IF NOT EXISTS share_links (
    token TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES export_jobs (id) ON DELETE CASCADE,
    redact INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT,
    views INTEGER NOT NULL DEFAULT 0,
    last_viewed_at TEXT
);

CREATE TABLE IF NOT EXISTS integrations (
    key TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    auto_sync INTEGER NOT NULL DEFAULT 0,
    last_sync_at TEXT,
    last_sync_fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template TEXT NOT NULL,
    destination TEXT NOT NULL,
    frequency TEXT NOT NULL,              -- daily | weekly | monthly
    options TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    created_at TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app) -> None:
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        db.commit()


def register_db(app) -> None:
    app.teardown_appcontext(close_db)
    init_db(app)
