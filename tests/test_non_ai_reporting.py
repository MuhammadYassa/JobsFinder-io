from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import Delivery, Posting, TaskRun, utc_now
from jobsfinder_io.registry import add_employer, add_source
from jobsfinder_io.relevance import assess_relevance, location_group
from jobsfinder_io.reporting.non_ai import generate_reports, notify_jobs


def seed(
    engine,
    *,
    identity="1",
    kind="new",
    revision=1,
    seen=None,
    changed=None,
    title="Backend Engineer",
    description="Python required. Three years preferred.",
    location="Germany",
    source_id=None,
    url=None,
):
    now = utc_now()
    with Session(engine) as session, session.begin():
        if source_id is None:
            employer = add_employer(session, f"Employer {identity}")
            source = add_source(
                session,
                employer.id,
                "greenhouse",
                f"board-{identity}",
                "https://example.test/careers",
            )
            source_id = source.id
        post = Posting(
            source_id=source_id,
            external_posting_id=identity,
            title=title,
            canonical_job_url=url or f"https://example.test/{identity}",
            apply_url=url or f"https://example.test/{identity}",
            description_text=description,
            date_provenance="unknown",
            first_seen_at=seen or now,
            last_seen_at=now,
            last_changed_at=changed or seen or now,
            content_hash=f"hash-{revision}",
            revision=revision,
            discovery_kind=kind,
            status="active",
            locations=location,
        )
        session.add(post)
        session.flush()
        return post.id, source_id


def test_local_report_no_ai_and_baseline_evidence(database, tmp_path, monkeypatch):
    engine = database[1]
    seed(engine, identity="baseline", kind="baseline", location="New York, NY")
    seed(engine, identity="intl")
    seed(
        engine,
        identity="unknown",
        location="Remote",
        title="Technology Associate",
        description="Assist technical teams.",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "must-never-be-used")
    result = generate_reports(engine, tmp_path, enqueue=False, slot_key="morning")
    body = __import__("pathlib").Path(result["path"]).read_text(encoding="utf-8")
    assert result["count"] == 3
    assert "Initial baseline — not newly published (1)" in body
    assert "Publication date unknown; freshness uncertain" in body
    assert "Source excerpt: Python required." in body
    assert "Source excerpt: Three years preferred." in body
    assert "https://example.test/intl" in body
    assert "Country unverified" in body
    assert "eligibility/sponsorship/start date unverified" in body
    assert generate_reports(engine, tmp_path, enqueue=False, slot_key="morning")[
        "duplicate"
    ]


def test_local_history_does_not_consume_email_and_pending_prevents_duplicates(
    database, tmp_path
):
    engine = database[1]
    seed(engine)
    generate_reports(engine, tmp_path, enqueue=False, slot_key="local")
    queued = generate_reports(engine, tmp_path, slot_key="morning")
    assert queued["count"] == 0
    assert queued["email_count"] == 1
    assert queued["email"]["status"] == "pending"
    assert generate_reports(engine, tmp_path, slot_key="morning")["duplicate"]
    second = generate_reports(engine, tmp_path, slot_key="evening")
    # Unattempted morning mail is replaced by one fresh evening report, with
    # its unreported job retained; it has never been delivered to the recipient.
    assert second["email_count"] == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Delivery)
                .where(Delivery.channel == "smtp_report")
            )
            == 1
        )


def test_alert_baselines_and_changed_revision(database, tmp_path):
    engine = database[1]
    baseline_id, _ = seed(engine, identity="baseline", kind="baseline")
    post_id, _ = seed(engine, identity="new")
    result = notify_jobs(engine, tmp_path)
    assert result["count"] == 1
    assert result["email_count"] == 1
    assert notify_jobs(engine, tmp_path)["count"] == 0
    with Session(engine) as session, session.begin():
        for identity in (baseline_id, post_id):
            post = session.get(Posting, identity)
            post.revision += 1
            post.content_hash = "changed"
    result = notify_jobs(engine, tmp_path)
    assert result["count"] == 2
    assert result["email_count"] == 2


def test_seven_day_missed_and_changed_jobs(database, tmp_path):
    engine = database[1]
    now = utc_now()
    seed(engine, identity="missed", seen=now - timedelta(days=6))
    seed(engine, identity="old", seen=now - timedelta(days=8))
    seed(
        engine,
        identity="changed",
        seen=now - timedelta(days=10),
        changed=now,
        revision=2,
    )
    assert generate_reports(engine, tmp_path, now=now, enqueue=False)["count"] == 2


def test_conservative_url_duplicate_prevention(database, tmp_path):
    engine = database[1]
    _, source_id = seed(engine, identity="one", url="https://example.test/same")
    seed(engine, identity="two", source_id=source_id, url="https://example.test/same")
    seed(engine, identity="distinct", source_id=source_id)
    assert generate_reports(engine, tmp_path, enqueue=False)["count"] == 2


def test_metrics_persisted_and_failed_email_keeps_receipt(database, tmp_path):
    engine = database[1]
    seed(engine)
    report = generate_reports(engine, tmp_path, slot_key="test")
    with Session(engine) as session:
        task = session.scalar(
            select(TaskRun).where(TaskRun.task_key == "nonai-report:test")
        )
        assert task.payload["metrics"] == report["metrics"]
        receipt = session.scalar(
            select(Delivery).where(Delivery.channel == "smtp_report")
        )
        assert receipt.status == "pending"
    assert report["metrics"]["new_postings"] == 1
    assert report["metrics"]["new_employers"] == 1


@pytest.mark.parametrize(
    "title,description,expected",
    [
        ("Java Engineer", "", "software evidence"),
        ("Graduate Technology Analyst", "", "uncertain relevance — review manually"),
        ("Integration Engineer", "", "software evidence"),
        ("Account Executive", "Sales targets", "unrelated"),
        ("Account Executive", "We build software and developer tools", "unrelated"),
        (
            "Accountant",
            "Develop Python applications for automation",
            "software evidence",
        ),
        ("Analyst", "Build Python applications", "software evidence"),
    ],
)
def test_relevance_preserves_uncertain(title, description, expected):
    assert assess_relevance(title, description) == expected


def test_locations_do_not_invent_countries():
    assert location_group("Remote")[0] == "unknown"
    assert location_group("Canada")[0] == "international"
    assert location_group("Austin, TX")[0] == "us"
    assert location_group("Canada / United States")[0] == "unknown"


def test_resume_after_enqueue_crash_preserves_local_report(
    database, tmp_path, monkeypatch
):
    from pathlib import Path

    from jobsfinder_io.reporting import non_ai

    engine = database[1]
    seed(engine)
    actual = non_ai.enqueue_email
    monkeypatch.setattr(
        non_ai,
        "enqueue_email",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")),
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        generate_reports(engine, tmp_path, slot_key="recover")
    artifact = next(
        path for path in tmp_path.glob("nonai-report-*.md") if "-email" not in path.name
    )
    body = artifact.read_text(encoding="utf-8")
    monkeypatch.setattr(non_ai, "enqueue_email", actual)
    result = generate_reports(engine, tmp_path, slot_key="recover")
    assert result["email"]["status"] == "pending"
    assert result["count"] == 1
    assert Path(result["path"]).read_text(encoding="utf-8") == body


def test_enqueue_conflict_remains_retriable(database, tmp_path, monkeypatch):
    from jobsfinder_io.reporting import non_ai

    seed(database[1])
    actual = non_ai.enqueue_email
    monkeypatch.setattr(non_ai, "enqueue_email", lambda *a, **k: {"status": "conflict"})
    with pytest.raises(RuntimeError, match="reservation conflict"):
        generate_reports(database[1], tmp_path, slot_key="conflict")
    monkeypatch.setattr(non_ai, "enqueue_email", actual)
    assert (
        generate_reports(database[1], tmp_path, slot_key="conflict")["email"]["status"]
        == "pending"
    )


def test_full_non_ai_discovery_poll_smtp_and_repeat_tick(
    database, tmp_path, monkeypatch
):
    import json
    from datetime import UTC, datetime

    import httpx

    from jobsfinder_io import delivery, operations
    from jobsfinder_io.delivery import SMTPConfig
    from jobsfinder_io.discovery import discover
    from jobsfinder_io.ingestion.polling import poll_source
    from jobsfinder_io.persistence.models import JobSource
    from jobsfinder_io.sources.greenhouse import GreenhouseCollector

    engine = database[1]
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.resolve_public", lambda host: "93.184.216.34"
    )
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.time.sleep", lambda delay: None
    )
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps([{"name": "Example", "careers_url": "https://example.com/careers"}])
    )
    jobs = [
        {
            "id": 101,
            "title": "Software Engineer",
            "absolute_url": "https://boards.greenhouse.io/example/jobs/101",
            "content": "<p>Build Python applications. Experience preferred.</p>",
            "location": {"name": "Canada"},
        }
    ]

    def http(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.host == "example.com":
            return httpx.Response(
                200,
                text='<a href="https://boards.greenhouse.io/example">Careers</a>',
                headers={"content-type": "text/html"},
            )
        if request.url.path.endswith("/jobs"):
            return httpx.Response(
                200, json={"jobs": jobs, "meta": {"total": len(jobs)}}
            )
        return httpx.Response(404)

    sent = []
    monkeypatch.setattr(
        delivery,
        "_send",
        lambda config, payload, now: sent.append(payload) or ("sent", None, False),
    )
    monkeypatch.setattr(
        delivery,
        "load_smtp_config",
        lambda: SMTPConfig(
            "smtp.example.test",
            587,
            "starttls",
            "from@example.test",
            "personal@example.test",
        ),
    )
    with httpx.Client(transport=httpx.MockTransport(http)) as client:
        assert discover(engine, candidates, client=client)["registered"] == 1
        with Session(engine) as session:
            source_id = session.scalar(select(JobSource.id))
        collector = GreenhouseCollector(client, request_interval=0)
        assert (
            poll_source(
                engine, source_id, collector=collector, detail_budget=0
            ).baseline
            == 1
        )
        jobs.append(
            {
                **jobs[0],
                "id": 102,
                "absolute_url": "https://boards.greenhouse.io/example/jobs/102",
            }
        )
        monkeypatch.setattr(
            operations,
            "poll_source",
            lambda engine, source_id: poll_source(
                engine, source_id, collector=collector, detail_budget=0
            ),
        )
        now = datetime.now(UTC).replace(hour=14, minute=0, second=0)
        with Session(engine) as session, session.begin():
            session.get(JobSource, source_id).last_attempt_at = now - timedelta(hours=2)
        first = operations.run_due(engine, output_dir=tmp_path, now=now)
        assert first["screening"]["api_calls"] == 0
        assert first["polling"]["success"] == 1
        assert first["notifications"]["count"] == 1
        assert first["reports"]["status"] == "complete"
        assert first["email"]["sent"] == 2
        assert len(sent) == 2
        with Session(engine) as session, session.begin():
            session.get(JobSource, source_id).last_attempt_at = now
        second = operations.run_due(
            engine, output_dir=tmp_path, now=now + timedelta(minutes=5)
        )
        assert second["reports"]["status"] == "already_complete"
        assert second["notifications"]["count"] == 0
        assert second["polling"]["due"] == 0
        assert len(sent) == 2
