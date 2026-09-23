import csv
import hashlib
import io
import json
import os
import tempfile
import zlib
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from expense_tracker import create_app
from expense_tracker.cloud import jobs, store
from expense_tracker.cloud.templates import TEMPLATES
from expense_tracker.formatting import format_relative
from expense_tracker.routes.exports import API_HEADER, API_HEADER_VALUE

THIS_YEAR = date.today().year


@pytest.fixture
def app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(
        {"TESTING": True, "DATABASE": db_path, "EXPORT_JOBS_INLINE": True, "EXPORT_SIMULATED_LATENCY": 0}
    )
    yield app
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suffix):
            os.unlink(db_path + suffix)


@pytest.fixture
def client(app):
    client = app.test_client()
    client.environ_base["HTTP_" + API_HEADER.upper().replace("-", "_")] = API_HEADER_VALUE
    return client


@pytest.fixture
def ctx(app):
    with app.test_request_context():
        yield


def add(client, description, amount, category, day):
    client.post(
        "/expenses/add",
        data={"description": description, "amount": str(amount), "category": category, "date": day},
    )


@pytest.fixture
def seeded(client):
    add(client, "Groceries", 80, "Food", f"{THIS_YEAR}-03-04")
    add(client, "Electric bill", 120, "Bills", f"{THIS_YEAR}-03-15")
    add(client, "Takeaway", 20, "Food", f"{THIS_YEAR}-02-10")
    add(client, "Old laptop", 900, "Shopping", f"{THIS_YEAR - 1}-11-01")
    return client


def start(client, template="tax-report", period=str(THIS_YEAR), destination="download", options=None, fmt=None):
    body = {"template": template, "period": period, "destination": destination, "options": options or {}}
    if fmt is not None:
        body["format"] = fmt
    return client.post("/exports/api/jobs", json=body)


def job_for(client, **kwargs):
    resp = start(client, **kwargs)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


def pdf_text(body: bytes) -> str:
    streams = [
        zlib.decompress(body[m.end() : m.end() + int(m.group(1))])
        for m in re.finditer(rb"<< /Length (\d+) /Filter /FlateDecode >>\nstream\n", body)
    ]
    return b"\n".join(streams).decode("latin-1")


# ---------- Templates on the shared engine ----------


def test_tax_report_defaults_to_pdf_for_one_year(seeded, ctx):
    report = TEMPLATES["tax-report"].build(str(THIS_YEAR), "pdf")
    assert report.count == 3
    assert (report.options.date_from, report.options.date_to) == (f"{THIS_YEAR}-01-01", f"{THIS_YEAR}-12-31")
    assert [e.date for e in report.expenses] == sorted(e.date for e in report.expenses)  # chronological
    assert ("Largest category", "Bills") in report.display_table.highlights

    job = store.get_job(job_for(seeded))
    assert (job.format, job.filename, job.mimetype) == ("pdf", f"tax-report-{THIS_YEAR}.pdf", "application/pdf")
    text = pdf_text(seeded.get(f"/exports/jobs/{job.id}/download").data)
    assert f"(Tax Report \\267 Tax year {THIS_YEAR})" in text  # template title in the PDF header
    assert "(Old laptop)" not in text


def test_monthly_summary_compares_with_previous_month(seeded, ctx):
    table = TEMPLATES["monthly-summary"].build(f"{THIS_YEAR}-03", "summary").display_table
    by_category = {row[0]: row for row in table.rows}
    assert by_category["Food"][2] == "$80.00"
    assert by_category["Food"][4] == "+300%"  # $20 in February -> $80 in March
    assert by_category["Bills"][4] == "new"
    assert ("vs. last month", "+900%") in table.highlights


def test_summary_csv_has_highlights_then_table(seeded, ctx):
    job_id = job_for(seeded, template="monthly-summary", period=f"{THIS_YEAR}-03")
    job = store.get_job(job_id)
    assert job.format == "summary" and job.filename == f"monthly-summary-{THIS_YEAR}-03.csv"
    rows = list(csv.reader(io.StringIO(seeded.get(f"/exports/jobs/{job_id}/download").data.decode("utf-8-sig"))))
    assert rows[0] == [job.title]
    assert ["vs. last month", "+900%"] in rows  # a signed percentage is data, not a formula
    assert ["Category", "Transactions", "Total", "Share", "vs. last month"] in rows


def test_category_analysis_all_time(seeded, ctx):
    table = TEMPLATES["category-analysis"].build("all", "summary").display_table
    assert [row[0] for row in table.rows] == ["Shopping", "Bills", "Food"]
    assert table.rows[2][3] == "$50.00"  # Food average
    assert ("Categories used", "3 of 6") in table.highlights


def test_full_backup_uses_engine_json(seeded, ctx):
    job_id = job_for(seeded, template="full-backup", period="all")
    data = json.loads(seeded.get(f"/exports/jobs/{job_id}/download").data)
    assert data["format"] == "expense-tracker-export"
    assert data["summary"]["record_count"] == 4
    assert {e["description"] for e in data["expenses"]} >= {"Groceries", "Old laptop"}


def test_report_csvs_neutralize_formulas(seeded, ctx):
    """D2: every template's CSV goes through the shared formula-safe writer."""
    add(seeded, '=HYPERLINK("http://x")', 5, "Food", f"{THIS_YEAR}-03-20")
    for template, period in (("tax-report", str(THIS_YEAR)), ("full-backup", "all")):
        job_id = job_for(seeded, template=template, period=period, fmt="csv")
        body = seeded.get(f"/exports/jobs/{job_id}/download").data.decode("utf-8-sig")
        assert "'=HYPERLINK" in body, template


# ---------- Validation ----------


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"template": "nope"}, "template"),
        ({"period": "1999"}, "period"),
        ({"fmt": "summary"}, "format"),  # not offered by the Tax Report
        ({"destination": "fax"}, "destination"),
        ({"destination": "dropbox"}, "destination"),  # not connected
        ({"destination": "email", "options": {"recipients": ""}}, "recipients"),
        ({"destination": "email", "options": {"recipients": "a@b.co, not-an-email"}}, "recipients"),
        ({"destination": "share", "options": {"expiry": "99"}}, "expiry"),
    ],
)
def test_start_job_validation(seeded, kwargs, field):
    resp = start(seeded, **kwargs)
    assert resp.status_code == 400
    assert field in resp.get_json()["errors"]


def test_google_sheets_needs_a_table_format(seeded, ctx):
    seeded.post("/exports/api/integrations/google-sheets/connect")
    assert "format" in start(seeded, destination="google-sheets", fmt="pdf").get_json()["errors"]
    job = store.get_job(job_for(seeded, destination="google-sheets"))  # default picks the tabular format
    assert job.format == "csv" and job.status == "done"


# ---------- Job lifecycle ----------


def test_download_job_completes_with_checksum_and_snapshot(seeded, ctx):
    job_id = job_for(seeded, fmt="csv")
    job = store.get_job(job_id)
    assert (job.status, job.progress, job.record_count) == ("done", 100, 3)
    body = seeded.get(f"/exports/jobs/{job_id}/download").data
    assert hashlib.sha256(body).hexdigest() == job.checksum
    assert job.size == len(body)
    assert {e.description for e in store.get_job_snapshot(job_id)} == {"Groceries", "Electric bill", "Takeaway"}


def test_email_job_records_delivery_and_renders_preview(seeded, ctx):
    job_id = job_for(
        seeded, destination="email", options={"recipients": "cpa@example.com; me@example.com", "message": "For Q1"}
    )
    job = store.get_job(job_id)
    assert job.result["recipients"] == ["cpa@example.com", "me@example.com"]
    assert job.result["subject"] == job.title
    html = seeded.get(f"/exports/jobs/{job_id}/preview").get_data(as_text=True)
    assert "Simulated delivery" in html and "cpa@example.com" in html and "For Q1" in html


@pytest.mark.parametrize("service", ["google-sheets", "dropbox", "onedrive", "slack"])
def test_service_destinations_require_connection_then_deliver(seeded, ctx, service):
    assert seeded.post(f"/exports/api/integrations/{service}/connect").status_code == 200
    job = store.get_job(job_for(seeded, destination=service))
    assert job.status == "done"
    assert seeded.get(f"/exports/jobs/{job.id}/preview").status_code == 200


def test_rerun_keeps_format_and_options(seeded, ctx):
    job_id = job_for(seeded, destination="email", options={"recipients": "a@b.co"}, fmt="json")
    rerun = store.get_job(seeded.post(f"/exports/api/jobs/{job_id}/rerun").get_json()["id"])
    assert (rerun.trigger, rerun.format, rerun.result["recipients"]) == ("rerun", "json", ["a@b.co"])
    assert seeded.delete(f"/exports/api/jobs/{job_id}").status_code == 200
    assert store.get_job(job_id) is None


# ---------- D1: CSRF ----------


def test_api_rejects_requests_without_the_api_header(app, seeded):
    plain = app.test_client()  # like a cross-site form post: no custom header
    resp = plain.post("/exports/api/integrations/dropbox/connect", data={})
    assert resp.status_code == 403
    assert not store_is_connected(app, "dropbox")


def test_api_rejects_cross_origin_requests(seeded):
    resp = seeded.post("/exports/api/integrations/dropbox/connect", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert seeded.post("/exports/api/integrations/dropbox/connect", headers={"Origin": "http://localhost"}).status_code == 200


def store_is_connected(app, key):
    with app.app_context():
        return store.is_connected(key)


# ---------- Sharing (D3, D4) ----------


def test_redacted_share_hides_descriptions_everywhere(seeded, ctx):
    job_id = job_for(seeded, destination="share", options={"expiry": "7", "redact": True}, fmt="csv")
    link = seeded.get(f"/exports/api/jobs/{job_id}/share").get_json()
    assert link["qr_svg"].startswith("<svg")

    page = seeded.get(f"/s/{link['token']}").get_data(as_text=True)
    assert "Electric bill" not in page and "Hidden" in page
    download = seeded.get(f"/s/{link['token']}/download")
    body = download.data.decode("utf-8-sig")
    assert "Electric bill" not in body and "[hidden]" in body
    assert download.headers["Content-Disposition"].endswith(f"tax-report-{THIS_YEAR}-shared.csv")


def test_redacted_share_download_is_complete_and_in_original_format(client, ctx):
    """D3: no 500-row cap, raw values, same format as the export."""
    with client.application.app_context():
        db = store.get_db()
        db.executemany(
            "INSERT INTO expenses (description, amount, category, date, created_at) VALUES (?, ?, ?, ?, ?)",
            [(f"Item {i}", 1.5, "Other", f"{THIS_YEAR}-01-01", "2026-01-01T00:00:00") for i in range(800)],
        )
        db.commit()
    job_id = job_for(client, template="full-backup", period="all", destination="share",
                     options={"expiry": "7", "redact": True})
    token = client.get(f"/exports/api/jobs/{job_id}/share").get_json()["token"]
    data = json.loads(client.get(f"/s/{token}/download").data)
    assert len(data["expenses"]) == 800
    assert {e["description"] for e in data["expenses"]} == {"[hidden]"}
    assert data["expenses"][0]["amount"] == 1.5


def test_redacted_download_uses_snapshot_not_current_data(seeded, ctx):
    job_id = job_for(seeded, template="full-backup", period="all")
    token = seeded.post(f"/exports/api/jobs/{job_id}/share", json={"expiry": "7", "redact": True}).get_json()["token"]
    add(seeded, "Added after the export", 1, "Other", f"{THIS_YEAR}-03-30")
    data = json.loads(seeded.get(f"/s/{token}/download").data)
    assert data["summary"]["record_count"] == 4


def test_unredacted_share_serves_original_file(seeded, ctx):
    job_id = job_for(seeded)
    link = seeded.post(f"/exports/api/jobs/{job_id}/share", json={"expiry": "never"}).get_json()
    assert link["expires"] == "Never expires"
    assert seeded.get(f"/s/{link['token']}/download").data == seeded.get(f"/exports/jobs/{job_id}/download").data


def test_share_views_count_people_not_bots_or_reloads(app, seeded, ctx):
    """D4"""
    token = seeded.post(f"/exports/api/jobs/{job_for(seeded)}/share", json={"expiry": "7"}).get_json()["token"]
    seeded.get(f"/s/{token}", headers={"User-Agent": "Slackbot-LinkExpanding 1.0"})
    seeded.get(f"/s/{token}", headers={"User-Agent": "facebookexternalhit/1.1"})
    assert store.get_share(token).views == 0
    seeded.get(f"/s/{token}", headers={"User-Agent": "Mozilla/5.0"})
    seeded.get(f"/s/{token}", headers={"User-Agent": "Mozilla/5.0"})  # reload: cookie already set
    assert store.get_share(token).views == 1
    app.test_client().get(f"/s/{token}", headers={"User-Agent": "Mozilla/5.0"})  # another browser
    assert store.get_share(token).views == 2


def test_revoked_and_expired_links_are_gone(seeded, ctx):
    job_id = job_for(seeded)
    revoked = seeded.post(f"/exports/api/jobs/{job_id}/share", json={"expiry": "1"}).get_json()["token"]
    seeded.post(f"/exports/api/shares/{revoked}/revoke")
    assert seeded.get(f"/s/{revoked}").status_code == 410

    expired = seeded.post(f"/exports/api/jobs/{job_id}/share", json={"expiry": "1"}).get_json()["token"]
    db = store.get_db()
    db.execute("UPDATE share_links SET expires_at = ? WHERE token = ?",
               (store.iso(store.now_utc() - timedelta(minutes=1)), expired))
    db.commit()
    resp = seeded.get(f"/s/{expired}")
    assert resp.status_code == 410 and b"expired" in resp.data
    assert seeded.get(f"/s/{expired}/download").status_code == 410
    assert seeded.get("/s/does-not-exist").status_code == 404


# ---------- D5: stale jobs across processes ----------


def test_startup_leaves_live_workers_alone_and_fails_dead_ones(app, ctx):
    live = store.insert_job("full-backup", "all", "json", "download", {}, "manual", "Live")
    dead = store.insert_job("full-backup", "all", "json", "download", {}, "manual", "Dead")
    store.update_job(live, status="running")
    store.update_job(dead, status="running", heartbeat_at=store.iso(store.now_utc() - timedelta(minutes=10)))

    create_app({"TESTING": True, "DATABASE": app.config["DATABASE"]})  # another process starting up

    assert store.get_job(live).status == "running"
    dead_job = store.get_job(dead)
    assert dead_job.status == "failed" and "stopped responding" in dead_job.error


def test_worker_does_not_revive_a_job_failed_elsewhere(app, ctx):
    job_id = store.insert_job("full-backup", "all", "json", "download", {}, "manual", "Backup")
    store.update_job(job_id, status="failed", error="Interrupted")
    jobs.run_job(app, job_id)
    job = store.get_job(job_id)
    assert (job.status, job.error, job.checksum) == ("failed", "Interrupted", None)


# ---------- D6 and schedules ----------


def test_next_run_after_clamps_month_end():
    jan31 = datetime(2026, 1, 31, 9, tzinfo=timezone.utc)
    assert jobs.next_run_after("monthly", jan31) == datetime(2026, 2, 28, 9, tzinfo=timezone.utc)
    assert jobs.next_run_after("weekly", jan31) == jan31 + timedelta(weeks=1)


def test_due_schedule_runs_once_and_catches_up(seeded, ctx):
    seeded.post("/exports/api/integrations/dropbox/connect")
    schedule_id = seeded.post(
        "/exports/api/schedules",
        json={"template": "monthly-summary", "destination": "dropbox", "frequency": "daily", "format": "pdf"},
    ).get_json()["id"]
    schedule = store.get_schedule(schedule_id)
    assert schedule.format == "pdf"

    three_days_late = schedule.next_run_at + timedelta(days=3, hours=1)
    started = jobs.run_due_schedules(three_days_late)
    assert len(started) == 1  # missed runs are caught up once, not replayed
    job = store.get_job(started[0])
    assert (job.trigger, job.status, job.format) == ("schedule", "done", "pdf")
    assert store.get_schedule(schedule_id).next_run_at > three_days_late
    assert jobs.run_due_schedules(three_days_late) == []


def test_schedule_claim_is_atomic(seeded, ctx):
    schedule_id = seeded.post(
        "/exports/api/schedules",
        json={"template": "full-backup", "destination": "email", "frequency": "daily", "options": {"recipients": "a@b.co"}},
    ).get_json()["id"]
    stale_view = store.get_schedule(schedule_id)  # what a second process read
    later = stale_view.next_run_at + timedelta(days=1)
    assert store.claim_schedule_run(stale_view, later) is True
    assert store.claim_schedule_run(stale_view, later) is False  # the other process loses


def test_schedule_to_disconnected_service_logs_failure(seeded, ctx):
    seeded.post("/exports/api/integrations/onedrive/connect")
    schedule_id = seeded.post(
        "/exports/api/schedules", json={"template": "full-backup", "destination": "onedrive", "frequency": "weekly"}
    ).get_json()["id"]
    seeded.post("/exports/api/integrations/onedrive/disconnect")
    job = store.get_job(seeded.post(f"/exports/api/schedules/{schedule_id}/run").get_json()["id"])
    assert job.status == "failed" and "Connect OneDrive" in job.error


def test_schedule_validation(seeded):
    resp = seeded.post("/exports/api/schedules", json={"template": "tax-report", "destination": "share", "frequency": "hourly"})
    assert set(resp.get_json()["errors"]) >= {"destination", "frequency"}


def test_resuming_a_schedule_does_not_fire_backlog(seeded, ctx):
    schedule_id = seeded.post(
        "/exports/api/schedules",
        json={"template": "full-backup", "destination": "email", "frequency": "daily", "options": {"recipients": "a@b.co"}},
    ).get_json()["id"]
    seeded.post(f"/exports/api/schedules/{schedule_id}/toggle")
    store.update_schedule(schedule_id, next_run_at=store.now_utc() - timedelta(days=5))
    seeded.post(f"/exports/api/schedules/{schedule_id}/toggle")
    schedule = store.get_schedule(schedule_id)
    assert schedule.enabled and schedule.next_run_at > store.now_utc()


# ---------- Change detection and live sync ----------


def test_data_version_changes_on_every_kind_of_edit(seeded, ctx):
    v1 = store.data_version()
    add(seeded, "Coffee", 4, "Food", f"{THIS_YEAR}-03-20")
    v2 = store.data_version()
    expense_id = store.get_db().execute("SELECT MAX(id) FROM expenses").fetchone()[0]
    seeded.post(f"/expenses/{expense_id}/edit",
                data={"description": "Coffee", "amount": "4.5", "category": "Food", "date": f"{THIS_YEAR}-03-20"})
    v3 = store.data_version()
    seeded.post(f"/expenses/{expense_id}/delete")
    assert len({v1, v2, v3, store.data_version()}) == 4


def test_sync_state_tracks_changes_after_sync(seeded, ctx):
    seeded.post("/exports/api/integrations/dropbox/connect")
    row = store.connected_services()["dropbox"]
    assert jobs.sync_state("dropbox", row, store.data_version())["state"] == "idle"

    job_for(seeded, template="full-backup", period="all", destination="dropbox")
    row = store.connected_services()["dropbox"]
    assert jobs.sync_state("dropbox", row, store.data_version())["state"] == "synced"

    add(seeded, "Coffee", 4, "Food", f"{THIS_YEAR}-03-20")
    assert jobs.sync_state("dropbox", row, store.data_version()) == {
        "state": "stale", "label": "1 new expense since last sync"
    }


def test_live_sync_mirrors_only_when_data_changed(seeded, ctx):
    seeded.post("/exports/api/integrations/google-sheets/connect")
    seeded.post("/exports/api/integrations/google-sheets/auto-sync", json={"enabled": True})
    first = store.list_jobs()
    assert len(first) == 1 and first[0].trigger == "auto-sync" and first[0].status == "done"
    assert first[0].format == "csv"  # Sheets gets a table even though backups default to JSON

    assert jobs.run_live_sync() == []
    add(seeded, "Coffee", 4, "Food", f"{THIS_YEAR}-03-20")
    assert len(jobs.run_live_sync()) == 1


def test_live_sync_not_available_for_messaging(seeded):
    seeded.post("/exports/api/integrations/slack/connect")
    assert seeded.post("/exports/api/integrations/slack/auto-sync", json={"enabled": True}).status_code == 400


# ---------- Retention ----------


def test_retention_removes_old_files_but_keeps_history_and_shared_exports(seeded, ctx):
    old = job_for(seeded, fmt="csv")
    shared = job_for(seeded, fmt="csv")
    seeded.post(f"/exports/api/jobs/{shared}/share", json={"expiry": "never"})
    recent = job_for(seeded, fmt="csv")
    db = store.get_db()
    long_ago = store.iso(store.now_utc() - timedelta(days=90))
    db.execute("UPDATE export_jobs SET created_at = ? WHERE id IN (?, ?)", (long_ago, old, shared))
    db.commit()

    assert store.prune_job_files(keep_count=50, max_age_days=30) == 1
    pruned = store.get_job(old)
    assert pruned.file_removed_at is not None and not pruned.has_file
    assert store.get_job_snapshot(old) is None
    assert seeded.get(f"/exports/jobs/{old}/download").status_code == 410
    assert store.get_job(shared).has_file and store.get_job(recent).has_file


def test_retention_keeps_only_the_most_recent_files(seeded, ctx):
    ids = [job_for(seeded, fmt="csv") for _ in range(4)]
    assert store.prune_job_files(keep_count=2, max_age_days=365) == 2
    assert [store.get_job(i).has_file for i in ids].count(True) == 2


# ---------- Pages ----------


def test_center_page_and_panels(seeded):
    html = seeded.get("/exports/").get_data(as_text=True)
    for text in ("Export Center", "Tax Report", "Monthly Summary", "Category Analysis", "Google Sheets", "xc-data"):
        assert text in html
    job_for(seeded)
    data = seeded.get("/exports/panels").get_json()
    assert set(data["panels"]) == {"status", "activity", "services", "schedules", "shares"}
    assert data["jobs"][0]["status"] == "done"
    assert "PDF" in data["panels"]["activity"]


def test_format_relative():
    now = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    assert format_relative(now - timedelta(seconds=10), now) == "just now"
    assert format_relative(now - timedelta(minutes=5), now) == "5 min ago"
    assert format_relative(now + timedelta(days=3), now) == "in 3 days"
    assert format_relative(None) == "never"
