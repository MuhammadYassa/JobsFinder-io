from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsfinder_io import operations
from jobsfinder_io.persistence.models import JobSource, PollRun, TaskRun
from jobsfinder_io.registry import add_employer, add_source, validate_source


@pytest.fixture
def source(database):
    with Session(database[1]) as session, session.begin():
        employer = add_employer(session, "Synthetic")
        source = add_source(
            session, employer.id, "greenhouse", "synthetic", "https://example.test"
        )
        validate_source(
            session,
            source.id,
            official_association_confirmed=True,
            public_access_confirmed=True,
        )
        return source.id


def test_intervals_failure_backoff_and_isolation(database, source, monkeypatch):
    now = datetime(2027, 1, 10, 15, tzinfo=UTC)
    with Session(database[1]) as session, session.begin():
        row = session.get(JobSource, source)
        row.last_attempt_at = now - timedelta(minutes=61)
        row.consecutive_failures = 1
    calls = []
    monkeypatch.setattr(
        operations,
        "poll_source",
        lambda e, i: calls.append(i) or SimpleNamespace(status="complete_success"),
    )
    assert operations.poll_due(database[1], now=now)["due"] == 0
    assert (
        operations.poll_due(database[1], now=now + timedelta(hours=1))["success"] == 1
    )
    assert calls == [source]


def test_abandoned_polls_recover_under_caller_lock(database, source, monkeypatch):
    now = datetime.now(UTC)
    with Session(database[1]) as session, session.begin():
        session.add(
            PollRun(
                source_id=source, started_at=now - timedelta(hours=1), status="running"
            )
        )
    monkeypatch.setattr(
        operations, "poll_source", lambda *a: SimpleNamespace(status="failed")
    )
    result = operations.poll_due(database[1], now=now)
    assert result["recovered"] == 1
    assert result["failed"] == 1
    with Session(database[1]) as session:
        assert (
            session.scalar(select(PollRun)).error_code
            == "interrupted_process_recovered"
        )


@pytest.mark.parametrize(
    ("instant", "slot"),
    [
        ("2027-03-13T14:59:00+00:00", None),
        ("2027-03-13T15:00:00+00:00", "report:2027-03-13:10"),
        ("2027-03-14T14:00:00+00:00", "report:2027-03-14:10"),
        ("2027-03-15T00:00:00+00:00", "report:2027-03-14:20"),
        ("2027-11-06T14:00:00+00:00", "report:2027-11-06:10"),
        ("2027-11-07T15:00:00+00:00", "report:2027-11-07:10"),
        ("2027-11-08T01:00:00+00:00", "report:2027-11-07:20"),
    ],
)
def test_new_york_report_slots_across_dst(instant, slot):
    assert operations.report_slot(datetime.fromisoformat(instant)) == slot


def test_persisted_daily_discovery_and_report_receipts(database, monkeypatch, tmp_path):
    import jobsfinder_io.discovery
    import jobsfinder_io.reporting.non_ai

    calls = []
    monkeypatch.setattr(
        jobsfinder_io.discovery,
        "discover",
        lambda *a, **k: calls.append("discover") or {"registered": 1},
    )
    monkeypatch.setattr(
        jobsfinder_io.reporting.non_ai,
        "generate_reports",
        lambda *a, **k: calls.append("report") or {"paths": []},
    )
    monkeypatch.setattr(
        jobsfinder_io.reporting.non_ai, "notify_jobs", lambda *a, **k: {"local": 0}
    )
    monkeypatch.setattr(operations, "poll_due", lambda *a, **k: {"due": 0})
    now = datetime(2027, 4, 1, 15, tzinfo=UTC)
    first = operations.run_due(
        database[1], now=now, candidates_path="synthetic.json", output_dir=tmp_path
    )
    second = operations.run_due(
        database[1], now=now, candidates_path="synthetic.json", output_dir=tmp_path
    )
    assert first["reports"]["status"] == "complete"
    assert second["reports"]["status"] == "already_complete"
    assert calls == ["discover", "report"]
    operations.run_due(
        database[1],
        now=now + timedelta(hours=10),
        candidates_path="synthetic.json",
        output_dir=tmp_path,
    )
    assert calls == ["discover", "report", "report"]


def test_failed_task_retries_and_sanitizes_error(database):
    now = datetime.now(UTC)

    def failure():
        raise RuntimeError("sensitive token should never persist")

    result = operations._task(database[1], "synthetic-task", now, failure)
    assert result["status"] == "failed"
    assert result["result"] == {"error": "RuntimeError"}
    assert (
        operations._task(database[1], "synthetic-task", now, lambda: {"ok": True})[
            "status"
        ]
        == "complete"
    )
    with Session(database[1]) as session:
        assert session.scalar(select(TaskRun)).payload == {"ok": True}


def test_missing_credentials_operate_offline(database, tmp_path):
    now = datetime(2027, 1, 1, 16, tzinfo=UTC)
    result = operations.run_due(database[1], now=now, output_dir=tmp_path)
    assert result["discovery"]["status"] == "not_configured"
    assert result["screening"]["skipped"] == 1
    assert result["reports"]["status"] == "complete"
    assert operations.health(database[1])["sources"] == 0


def test_naive_time_rejected(database):
    with pytest.raises(ValueError, match="timezone"):
        operations.poll_due(database[1], now=datetime(2027, 1, 1))


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2027-03-13T10:59:00+00:00", None),
        ("2027-03-13T11:00:00+00:00", "discovery:2027-03-13"),
        ("2027-03-14T10:00:00+00:00", "discovery:2027-03-14"),
        ("2027-11-07T10:59:00+00:00", None),
        ("2027-11-07T11:00:00+00:00", "discovery:2027-11-07"),
    ],
)
def test_discovery_six_am_across_dst(instant, expected):
    assert operations.discovery_slot(datetime.fromisoformat(instant)) == expected


def test_monitoring_never_invokes_screening_even_with_credentials(
    database, tmp_path, monkeypatch
):
    def reject(*args, **kwargs):
        pytest.fail("Non-AI monitoring must never invoke screening")

    monkeypatch.setattr("jobsfinder_io.screening.screen_jobs", reject)
    monkeypatch.setattr("jobsfinder_io.screening.batch.screen_batch", reject)
    monkeypatch.setattr("jobsfinder_io.screening.genai.Client", reject)
    result = operations.run_due(
        database[1],
        output_dir=tmp_path,
        api_key="synthetic",
        max_calls=999,
        now=datetime(2027, 1, 1, 9, tzinfo=UTC),
        local_only=True,
    )
    assert result["screening"] == {"status": "disabled", "skipped": 1, "api_calls": 0}
    assert result["email"]["status"] == "local_only"
    assert result["screening_queue"] == {"candidates": 0}


def test_discovery_not_run_before_six(database, tmp_path, monkeypatch):
    import jobsfinder_io.discovery

    monkeypatch.setattr(
        jobsfinder_io.discovery, "discover", lambda *a, **k: pytest.fail("too early")
    )
    result = operations.run_due(
        database[1],
        candidates_path="unused.json",
        output_dir=tmp_path,
        now=datetime(2027, 1, 1, 10, 59, tzinfo=UTC),
        local_only=True,
    )
    assert result["discovery"]["status"] == "not_due"


def test_local_tick_does_not_consume_scheduled_email_report(database, tmp_path):
    now = datetime(2027, 1, 1, 15, tzinfo=UTC)
    first = operations.run_due(
        database[1], output_dir=tmp_path, now=now, local_only=True
    )
    assert first["reports"]["status"] == "complete"
    second = operations.run_due(database[1], output_dir=tmp_path, now=now)
    assert second["reports"]["status"] == "complete"
    with Session(database[1]) as session:
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "report:2027-01-01:10")
            )
            is not None
        )
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "local:report:2027-01-01:10")
            )
            is not None
        )


def test_one_source_exception_does_not_stop_others(database, source, monkeypatch):
    with Session(database[1]) as session, session.begin():
        employer = add_employer(session, "Another synthetic")
        other = add_source(
            session, employer.id, "greenhouse", "other", "https://example.test"
        )
        validate_source(
            session,
            other.id,
            official_association_confirmed=True,
            public_access_confirmed=True,
        )

    def poll(engine, identity):
        if identity == source:
            raise RuntimeError("Synthetic fetch failure")
        return SimpleNamespace(status="complete_success")

    monkeypatch.setattr(operations, "poll_source", poll)
    result = operations.poll_due(database[1])
    assert result["due"] == 2
    assert result["success"] == result["failed"] == 1
