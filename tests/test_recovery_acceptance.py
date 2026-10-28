"""Recovery acceptance checks use disposable databases and no external services."""

import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta

import pytest
from alembic import command
from conftest import migration_config
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_email import item

from jobsfinder_io.delivery import (
    SMTPConfig,
    deliver_pending,
    enqueue_email,
    supersede_unsent_alerts,
    supersede_unsent_reports,
)
from jobsfinder_io.persistence.database import make_engine
from jobsfinder_io.persistence.models import (
    Delivery,
    Employer,
    Posting,
    TaskRun,
    utc_now,
)
from jobsfinder_io.registry import add_employer
from jobsfinder_io.runlock import RunInProgress, database_run_lock


def test_backup_restore_preserves_jobs_and_pending_outbox_without_changing_source(
    database, tmp_path
):
    path, engine = database
    receipt = item(engine)
    enqueue_email(
        engine,
        "before-backup",
        "Recovery example",
        "Stored report body",
        items=[receipt],
    )
    snapshot = tmp_path / "snapshot.db"
    restored_path = tmp_path / "restored.db"
    with sqlite3.connect(path) as source, sqlite3.connect(snapshot) as destination:
        source.backup(destination)
    with Session(engine) as session, session.begin():
        add_employer(session, "Created after snapshot")
    with (
        sqlite3.connect(snapshot) as source,
        sqlite3.connect(restored_path) as destination,
    ):
        source.backup(destination)
    command.upgrade(migration_config(restored_path), "head")
    restored = make_engine(restored_path)
    try:
        with Session(restored) as session:
            assert session.scalar(select(func.count()).select_from(Posting)) == 1
            assert session.scalar(select(func.count()).select_from(Employer)) == 1
            assert session.scalar(select(Delivery)).status == "pending"
            task = session.scalar(
                select(TaskRun).where(TaskRun.task_key == "email:before-backup")
            )
            assert task.status == "pending"
            assert task.payload["body"] == "Stored report body"
            assert task.payload["items"] == [receipt]
        with restored.connect() as connection:
            assert (
                connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
                == "ok"
            )
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with Session(restored) as session, session.begin():
            session.get(
                Posting, receipt["posting_id"]
            ).title = "Changed only in restored copy"
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Employer)) == 2
            assert (
                session.get(Posting, receipt["posting_id"]).title == "Software Engineer"
            )
        assert deliver_pending(restored, None)["missing_config"] is True
    finally:
        restored.dispose()


def test_process_kill_releases_database_lock_without_deleting_lockfile(tmp_path):
    path = tmp_path / "kill-recovery.db"
    code = "\n".join(
        [
            "import sys,time",
            "from jobsfinder_io.runlock import database_run_lock",
            "with database_run_lock(sys.argv[1]):",
            "    print('locked',flush=True)",
            "    time.sleep(30)",
        ]
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(RunInProgress), database_run_lock(path):
            pytest.fail("Second process acquired an active lock")
        child.kill()
        child.wait(timeout=5)
        with database_run_lock(path):
            assert path.with_suffix(".run.lock").is_file()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if child.stdout:
            child.stdout.close()


def test_recipient_change_failure_updates_group_and_individual_delivery_history(
    database, monkeypatch
):
    engine = database[1]
    receipt = item(engine)
    enqueue_email(engine, "recipient-change", "Example alert", "Body", items=[receipt])
    config = SMTPConfig(
        "smtp.example.test",
        587,
        "starttls",
        "from@example.test",
        "personal@example.test",
    )
    monkeypatch.setattr(
        "jobsfinder_io.delivery._send", lambda *args: ("failed", "TimeoutError", True)
    )
    now = utc_now()
    assert deliver_pending(engine, config, now=now)["failed"] == 1

    def forbidden(*args):
        pytest.fail("A queued message must never be rerouted to a changed recipient")

    monkeypatch.setattr("jobsfinder_io.delivery._send", forbidden)
    result = deliver_pending(
        engine,
        replace(config, recipient="changed@example.test"),
        now=now + timedelta(minutes=6),
    )
    assert result["failed"] == 1
    with Session(engine) as session:
        task = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "email:recipient-change")
        )
        assert task.status == "failed"
        assert task.payload["error"] == "recipient_changed"
        assert task.payload["history"][-1]["error"] == "recipient_changed"
        assert task.completed_at == now + timedelta(minutes=6)
        delivery = session.scalar(select(Delivery))
        assert delivery.status == "failed" and delivery.sent_at is None


def test_fresh_report_replaces_only_unattempted_reports_and_reuses_receipts(database):
    engine = database[1]
    alert_item = item(engine)
    report_item = {**alert_item, "channel": "smtp_report"}
    attempted_item = {**report_item, "pipeline": "international"}
    enqueue_email(
        engine,
        "nonai-report:old",
        "Old digest",
        "Old report body",
        items=[report_item],
        artifact_path="old.md",
    )
    enqueue_email(
        engine,
        "nonai-report:attempted",
        "Attempted digest",
        "Keep attempted body",
        items=[attempted_item],
    )
    enqueue_email(engine, "alert", "Alert", "Keep alert body", items=[alert_item])
    with Session(engine) as session, session.begin():
        attempted = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "email:nonai-report:attempted")
        )
        attempted.status = "failed"
        attempted.payload = {**attempted.payload, "attempts": 1}
        original_id = session.scalar(select(Delivery.id).filter_by(**report_item))
    assert supersede_unsent_reports(engine, "nonai-report:new") == 1
    with Session(engine) as session:
        old = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "email:nonai-report:old")
        )
        assert old.status == "superseded" and old.payload["body"] == "Old report body"
        assert old.payload["artifact_path"] == "old.md"
        assert session.get(Delivery, original_id).status == "superseded"
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "email:alert")
            ).status
            == "pending"
        )
        assert (
            session.scalar(
                select(TaskRun).where(
                    TaskRun.task_key == "email:nonai-report:attempted"
                )
            ).status
            == "failed"
        )
    result = enqueue_email(
        engine,
        "nonai-report:new",
        "Fresh digest",
        "Fresh report body",
        items=[report_item],
        artifact_path="new.md",
    )
    assert result["queued"] is True
    assert supersede_unsent_reports(engine, "nonai-report:new") == 0
    with Session(engine) as session:
        receipt = session.get(Delivery, original_id)
        assert receipt.status == "pending" and receipt.artifact_path == "new.md"
        assert session.scalar(select(func.count()).select_from(Delivery)) == 3


@pytest.mark.parametrize("status", ["pending", "failed", "sent", "uncertain"])
def test_replacement_never_replays_an_attempted_group(database, status):
    engine = database[1]
    report_item = {**item(engine), "channel": "smtp_report"}
    enqueue_email(
        engine, "nonai-report:attempted", "Attempted", "Saved body", items=[report_item]
    )
    with Session(engine) as session, session.begin():
        task = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "email:nonai-report:attempted")
        )
        task.status = status
        task.payload = {**task.payload, "attempts": 1}
    assert supersede_unsent_reports(engine, "nonai-report:new") == 0
    assert (
        enqueue_email(
            engine, "nonai-report:new", "New", "New body", items=[report_item]
        )["status"]
        == "conflict"
    )


def test_receipt_reactivation_is_atomic_when_another_item_conflicts(database):
    engine = database[1]
    report_item = {**item(engine), "channel": "smtp_report"}
    blocked_item = {**report_item, "pipeline": "international"}
    enqueue_email(engine, "nonai-report:old", "Old", "Old body", items=[report_item])
    supersede_unsent_reports(engine, "nonai-report:fresh")
    enqueue_email(engine, "attempted", "Keep", "Keep body", items=[blocked_item])
    result = enqueue_email(
        engine,
        "nonai-report:fresh",
        "Fresh",
        "Fresh body",
        items=[report_item, blocked_item],
    )
    assert result["status"] == "conflict"
    with Session(engine) as session:
        assert (
            session.scalar(select(Delivery).filter_by(**report_item)).status
            == "superseded"
        )
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "email:nonai-report:fresh")
            )
            is None
        )


def test_alert_backlog_coalesces_without_touching_reports_or_attempted_alerts(database):
    engine = database[1]
    alert_item = item(engine)
    attempted_item = {**alert_item, "pipeline": "international"}
    report_item = {**alert_item, "channel": "smtp_report"}
    enqueue_email(
        engine, "nonai-alert:old", "Old", "Never sent old alert", items=[alert_item]
    )
    enqueue_email(
        engine,
        "nonai-alert:attempted",
        "Attempted",
        "Keep attempts",
        items=[attempted_item],
    )
    enqueue_email(
        engine, "nonai-report:pending", "Report", "Keep report", items=[report_item]
    )
    with Session(engine) as session, session.begin():
        task = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "email:nonai-alert:attempted")
        )
        task.payload = {**task.payload, "attempts": 1}
    assert supersede_unsent_alerts(engine, "nonai-alert:new") == 1
    assert (
        enqueue_email(
            engine, "nonai-alert:new", "Fresh", "New grouped alert", items=[alert_item]
        )["queued"]
        is True
    )
    assert supersede_unsent_alerts(engine, "nonai-alert:new") == 0
    with Session(engine) as session:
        old = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "email:nonai-alert:old")
        )
        assert old.status == "superseded"
        assert old.payload["body"] == "Never sent old alert"
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "email:nonai-report:pending")
            ).status
            == "pending"
        )
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "email:nonai-alert:attempted")
            ).status
            == "pending"
        )


def test_alert_group_can_return_to_an_older_job_set_after_a_job_closes(
    database, tmp_path
):
    from test_non_ai_reporting import seed

    from jobsfinder_io.reporting.non_ai import notify_jobs

    engine = database[1]
    seed(engine, identity="a", title="Backend Engineer A")
    seed(engine, identity="b", title="Backend Engineer B")
    now = utc_now()
    notify_jobs(engine, tmp_path, now=now)
    closed_id, _ = seed(engine, identity="c", title="Backend Engineer C")
    notify_jobs(engine, tmp_path, now=now + timedelta(minutes=1))
    with Session(engine) as session, session.begin():
        session.get(Posting, closed_id).status = "closed"
    notify_jobs(engine, tmp_path, now=now + timedelta(minutes=2))
    with Session(engine) as session:
        pending = list(
            session.scalars(
                select(TaskRun).where(
                    TaskRun.task_key.startswith("email:nonai-alert:"),
                    TaskRun.status == "pending",
                )
            )
        )
        assert len(pending) == 1
        assert "Backend Engineer A" in pending[0].payload["body"]
        assert "Backend Engineer B" in pending[0].payload["body"]
        assert "Backend Engineer C" not in pending[0].payload["body"]
