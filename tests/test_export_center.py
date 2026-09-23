import csv
import hashlib
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest

from expense_tracker import create_app
from expense_tracker.cloud import jobs, store
from expense_tracker.cloud.templates import TEMPLATES
from expense_tracker.formatting import format_relative

THIS_YEAR = date.today().year


@pytest.fixture
def app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(
        {"TESTING": True, "DATABASE": db_path, "EXPORT_JOBS_INLINE": True, "EXPORT_SIMULATED_LATENCY": 0}
    )
    yield app
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


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


def start(client, template="tax-report", period=str(THIS_YEAR), destination="download", options=None):
    return client.post(
        "/exports/api/jobs",
        json={"template": template, "period": period, "destination": destination, "options": options or {}},
    )


def job_for(client, **kwargs):
    resp = start(client, **kwargs)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


# ---------- Templates ----------


def test_tax_report_covers_one_year_with_subtotals(seeded, ctx):
    artifact = TEMPLATES["tax-report"].build(str(THIS_YEAR))
    assert artifact.record_count == 3
    assert artifact.filename == f"tax-report-{THIS_YEAR}.csv"
    rows = list(csv.reader(io.StringIO(artifact.content.decode("utf-8-sig"))))
    assert ["Bills", "1", "120.00"] in rows
    assert ["Food", "2", "100.00"] in rows
    assert ["Total", "3", "220.00"] in rows
    assert not any("Old laptop" in r for r in map(" ".join, rows))
    assert ("Largest category", "Bills") in artifact.highlights


def test_monthly_summary_compares_with_previous_month(seeded, ctx):
    artifact = TEMPLATES["monthly-summary"].build(f"{THIS_YEAR}-03")
    assert artifact.record_count == 2
    by_category = {row[0]: row for row in artifact.rows}
    assert by_category["Food"][2] == "$80.00"
    assert by_category["Food"][4] == "+300%"  # $20 in February -> $80 in March
    assert by_category["Bills"][4] == "new"
    assert ("vs. last month", "+900%") in artifact.highlights


def test_category_analysis_all_time(seeded, ctx):
    artifact = TEMPLATES["category-analysis"].build("all")
    assert [row[0] for row in artifact.rows] == ["Shopping", "Bills", "Food"]
    assert artifact.rows[2][3] == "$50.00"  # Food average
    assert ("Categories used", "3 of 6") in artifact.highlights


def test_full_backup_is_restorable_json(seeded, ctx):
    data = json.loads(TEMPLATES["full-backup"].build("all").content)
    assert data["format"] == "expense-tracker-backup"
    assert data["record_count"] == 4
    assert {e["description"] for e in data["expenses"]} >= {"Groceries", "Old laptop"}


# ---------- Validation ----------


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"template": "nope"}, "template"),
        ({"period": "1999"}, "period"),
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


# ---------- Job lifecycle ----------


def test_download_job_completes_with_checksum(seeded, ctx):
    job_id = job_for(seeded)
    job = store.get_job(job_id)
    assert (job.status, job.progress, job.record_count) == ("done", 100, 3)
    body = seeded.get(f"/exports/jobs/{job_id}/download").data
    assert hashlib.sha256(body).hexdigest() == job.checksum
    assert job.size == len(body)


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
    job_id = job_for(seeded, destination=service)
    job = store.get_job(job_id)
    assert job.status == "done"
    assert seeded.get(f"/exports/jobs/{job_id}/preview").status_code == 200


def test_rerun_and_delete(seeded, ctx):
    job_id = job_for(seeded, destination="email", options={"recipients": "a@b.co"})
    rerun = seeded.post(f"/exports/api/jobs/{job_id}/rerun").get_json()["id"]
    assert store.get_job(rerun).trigger == "rerun"
    assert store.get_job(rerun).result["recipients"] == ["a@b.co"]
    assert seeded.delete(f"/exports/api/jobs/{job_id}").status_code == 200
    assert store.get_job(job_id) is None


def test_orphaned_jobs_fail_on_startup(app, ctx):
    job_id = store.insert_job("full-backup", "all", "download", {}, "manual", "Backup")
    store.fail_orphaned_jobs()
    job = store.get_job(job_id)
    assert job.status == "failed" and "restart" in job.error


# ---------- Sharing ----------


def test_share_link_redacts_descriptions(seeded, ctx):
    job_id = job_for(seeded, destination="share", options={"expiry": "7", "redact": True})
    link = seeded.get(f"/exports/api/jobs/{job_id}/share").get_json()
    assert link["qr_svg"].startswith("<svg")
    assert link["url"].endswith(f"/s/{link['token']}")

    page = seeded.get(f"/s/{link['token']}").get_data(as_text=True)
    assert "Electric bill" not in page and "Hidden" in page
    download = seeded.get(f"/s/{link['token']}/download").data.decode("utf-8-sig")
    assert "Electric bill" not in download and "[hidden]" in download
    assert store.get_share(link["token"]).views == 1


def test_share_link_without_redaction_serves_original(seeded, ctx):
    job_id = job_for(seeded)
    link = seeded.post(f"/exports/api/jobs/{job_id}/share", json={"expiry": "never"}).get_json()
    assert link["expires"] == "Never expires"
    assert "Electric bill" in seeded.get(f"/s/{link['token']}").get_data(as_text=True)
    original = seeded.get(f"/exports/jobs/{job_id}/download").data
    assert seeded.get(f"/s/{link['token']}/download").data == original


def test_revoked_and_expired_links_are_gone(seeded, app, ctx):
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


# ---------- Sync status and live sync ----------


def test_sync_state_tracks_changes_after_sync(seeded, ctx):
    seeded.post("/exports/api/integrations/dropbox/connect")
    row = store.connected_services()["dropbox"]
    assert jobs.sync_state("dropbox", row, store.expenses_fingerprint())["state"] == "idle"

    job_for(seeded, template="full-backup", period="all", destination="dropbox")
    row = store.connected_services()["dropbox"]
    assert jobs.sync_state("dropbox", row, store.expenses_fingerprint())["state"] == "synced"

    add(seeded, "Coffee", 4, "Food", f"{THIS_YEAR}-03-20")
    state = jobs.sync_state("dropbox", row, store.expenses_fingerprint())
    assert state == {"state": "stale", "label": "1 new expense since last sync"}


def test_live_sync_mirrors_only_when_data_changed(seeded, ctx):
    seeded.post("/exports/api/integrations/google-sheets/connect")
    seeded.post("/exports/api/integrations/google-sheets/auto-sync", json={"enabled": True})
    first = store.list_jobs()
    assert len(first) == 1 and first[0].trigger == "auto-sync" and first[0].status == "done"

    assert jobs.run_live_sync() == []  # nothing changed
    add(seeded, "Coffee", 4, "Food", f"{THIS_YEAR}-03-20")
    assert len(jobs.run_live_sync()) == 1


def test_live_sync_not_available_for_messaging(seeded):
    seeded.post("/exports/api/integrations/slack/connect")
    assert seeded.post("/exports/api/integrations/slack/auto-sync", json={"enabled": True}).status_code == 400


# ---------- Schedules ----------


def test_next_run_after_clamps_month_end():
    jan31 = datetime(2026, 1, 31, 9, tzinfo=timezone.utc)
    assert jobs.next_run_after("monthly", jan31) == datetime(2026, 2, 28, 9, tzinfo=timezone.utc)
    assert jobs.next_run_after("weekly", jan31) == jan31 + timedelta(weeks=1)


def test_due_schedule_runs_once_and_catches_up(seeded, ctx):
    seeded.post("/exports/api/integrations/dropbox/connect")
    schedule_id = seeded.post(
        "/exports/api/schedules", json={"template": "monthly-summary", "destination": "dropbox", "frequency": "daily"}
    ).get_json()["id"]
    schedule = store.get_schedule(schedule_id)

    three_days_late = schedule.next_run_at + timedelta(days=3, hours=1)
    started = jobs.run_due_schedules(three_days_late)
    assert len(started) == 1  # missed runs are caught up once, not replayed
    job = store.get_job(started[0])
    assert (job.trigger, job.status) == ("schedule", "done")
    assert store.get_schedule(schedule_id).next_run_at > three_days_late
    assert jobs.run_due_schedules(three_days_late) == []


def test_schedule_to_disconnected_service_logs_failure(seeded, ctx):
    seeded.post("/exports/api/integrations/onedrive/connect")
    schedule_id = seeded.post(
        "/exports/api/schedules", json={"template": "full-backup", "destination": "onedrive", "frequency": "weekly"}
    ).get_json()["id"]
    seeded.post("/exports/api/integrations/onedrive/disconnect")
    job_id = seeded.post(f"/exports/api/schedules/{schedule_id}/run").get_json()["id"]
    job = store.get_job(job_id)
    assert job.status == "failed" and "Connect OneDrive" in job.error


def test_schedule_validation(seeded):
    resp = seeded.post("/exports/api/schedules", json={"template": "tax-report", "destination": "share", "frequency": "hourly"})
    assert set(resp.get_json()["errors"]) >= {"destination", "frequency"}


def test_resuming_a_schedule_does_not_fire_backlog(seeded, ctx):
    schedule_id = seeded.post(
        "/exports/api/schedules",
        json={"template": "full-backup", "destination": "email", "frequency": "daily", "options": {"recipients": "a@b.co"}},
    ).get_json()["id"]
    seeded.post(f"/exports/api/schedules/{schedule_id}/toggle")  # pause
    store.update_schedule(schedule_id, next_run_at=store.now_utc() - timedelta(days=5))
    seeded.post(f"/exports/api/schedules/{schedule_id}/toggle")  # resume
    schedule = store.get_schedule(schedule_id)
    assert schedule.enabled and schedule.next_run_at > store.now_utc()


# ---------- Pages ----------


def test_center_page_and_panels(seeded):
    html = seeded.get("/exports/").get_data(as_text=True)
    for text in ("Export Center", "Tax Report", "Monthly Summary", "Category Analysis", "Google Sheets", "xc-data"):
        assert text in html
    job_for(seeded)
    data = seeded.get("/exports/panels").get_json()
    assert set(data["panels"]) == {"status", "activity", "services", "schedules", "shares"}
    assert data["jobs"][0]["status"] == "done"
    assert data["active"] == 0


def test_nav_and_dashboard_link_to_export_center(seeded):
    html = seeded.get("/").get_data(as_text=True)
    assert "/exports/" in html and "Export &amp; share" in html


def test_format_relative():
    now = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    assert format_relative(now - timedelta(seconds=10), now) == "just now"
    assert format_relative(now - timedelta(minutes=5), now) == "5 min ago"
    assert format_relative(now + timedelta(days=3), now) == "in 3 days"
    assert format_relative(None) == "never"
