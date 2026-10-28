"""Offline discovery-to-delivery acceptance with actual service boundaries."""

import json
import smtplib
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io import operations
from jobsfinder_io.delivery import SMTPConfig
from jobsfinder_io.discovery import discover
from jobsfinder_io.ingestion.polling import poll_source
from jobsfinder_io.persistence.models import (
    Delivery,
    JobSource,
    Posting,
    ScreeningResult,
    TaskRun,
    utc_now,
)
from jobsfinder_io.sources.greenhouse import GreenhouseCollector


def test_discovery_poll_baseline_new_alert_report_and_recovery(
    database, tmp_path, monkeypatch
):
    engine = database[1]
    payload = json.loads(
        (Path(__file__).parent / "fixtures/greenhouse_jobs.json").read_text()
    )
    payload["jobs"] = payload["jobs"][:1]
    payload["meta"]["total"] = 1
    requests = []

    def http(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.host == "example.com":
            return httpx.Response(
                200,
                text='<a href="https://boards.greenhouse.io/example">Jobs</a>',
                headers={"content-type": "text/html"},
            )
        assert request.url.host == "boards-api.greenhouse.io"
        return httpx.Response(200, json=payload)

    class SMTP:
        accepted = []
        fail = False

        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            pass

        def starttls(self, *, context):
            assert context.check_hostname

        def mail(self, sender):
            if self.fail:
                raise TimeoutError("synthetic")
            return 250, b"OK"

        def rcpt(self, recipient):
            assert recipient == "personal@example.test"
            return 250, b"OK"

        def data(self, message):
            self.accepted.append(message)
            return 250, b"accepted"

        def close(self):
            pass

    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.resolve_public", lambda host: "93.184.216.34"
    )
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.time.sleep", lambda value: None
    )
    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    monkeypatch.setattr(
        "jobsfinder_io.delivery.load_smtp_config",
        lambda: SMTPConfig(
            "smtp.example.test",
            587,
            "starttls",
            "from@example.test",
            "personal@example.test",
        ),
    )
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps([{"name": "Example", "careers_url": "https://example.com/careers"}])
    )
    with httpx.Client(transport=httpx.MockTransport(http)) as client:
        assert discover(engine, candidates, client=client)["registered"] == 1
        assert discover(engine, candidates, client=client)["registered"] == 0
        with Session(engine) as session:
            source_id = session.scalar(select(JobSource.id))
        collector = GreenhouseCollector(
            client, request_interval=0, sleep=lambda seconds: None
        )
        assert poll_source(engine, source_id, collector=collector).baseline == 1
        new = deepcopy(payload["jobs"][0])
        new.update(
            id=201,
            internal_job_id=901,
            title="Junior Backend Software Engineer",
            content="Build Python REST API services; sponsorship status unspecified.",
            absolute_url="https://job-boards.greenhouse.io/example/jobs/201",
        )
        payload["jobs"].append(new)
        payload["meta"]["total"] = 2
        assert poll_source(engine, source_id, collector=collector).new == 1
        assert poll_source(engine, source_id, collector=collector).unchanged == 2
        # Simulate a process restart at a report slot; polling remains in-process mocked HTTP.
        monkeypatch.setattr(
            operations,
            "poll_source",
            lambda engine, identity: poll_source(engine, identity, collector=collector),
        )
        now = utc_now()
        from zoneinfo import ZoneInfo

        now = now.astimezone(ZoneInfo("America/New_York")).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        if now < utc_now():
            now += timedelta(days=1)
        SMTP.fail = True
        first = operations.run_due(engine, now=now, output_dir=tmp_path / "reports")
        assert first["screening"]["api_calls"] == 0
        assert first["email"]["failed"] == 2  # One grouped alert and one full report.
        assert not SMTP.accepted
        SMTP.fail = False
        second = operations.run_due(
            engine, now=now + timedelta(minutes=5), output_dir=tmp_path / "reports"
        )
        assert second["reports"]["status"] == "already_complete"
        assert second["email"]["sent"] == 2
        assert second["screening"]["api_calls"] == 0
        third = operations.run_due(
            engine, now=now + timedelta(minutes=10), output_dir=tmp_path / "reports"
        )
        assert third["email"]["sent"] == 0
    assert len(SMTP.accepted) == 2
    assert len(list((tmp_path / "reports").glob("*.md"))) >= 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Posting)) == 2
        assert session.scalar(select(func.count()).select_from(ScreeningResult)) == 0
        receipts = session.scalars(
            select(Delivery).where(Delivery.channel.like("smtp_%"))
        ).all()
        assert len(receipts) == 3  # New job alert, plus baseline and new job report.
        assert all(receipt.status == "sent" for receipt in receipts)
        assert all(
            row.payload["attempts"] == 2
            for row in session.scalars(
                select(TaskRun).where(TaskRun.task_key.like("email:%"))
            )
        )
    assert all("example.com" in url or "greenhouse.io" in url for url in requests)
