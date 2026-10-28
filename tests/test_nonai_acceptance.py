"""Independent non-AI acceptance: content, temporal scope and personal delivery.

All email is mocked. No environment file, live service or real database is used.
"""

import smtplib
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsfinder_io import operations
from jobsfinder_io.delivery import SMTPConfig, deliver_pending
from jobsfinder_io.persistence.models import Delivery, Posting, TaskRun
from jobsfinder_io.registry import add_employer, add_source
from jobsfinder_io.relevance import (
    assess_relevance,
    location_group,
    requirement_excerpts,
)
from jobsfinder_io.reporting.non_ai import generate_reports, notify_jobs


@pytest.fixture(autouse=True)
def nonai_only(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_MAX_CALLS", "0")
    monkeypatch.setenv("GEMINI_BATCH_ENABLED", "false")


@pytest.mark.parametrize(
    "location,country",
    [
        ("MY; Shah Alam, Selangor, Malaysia; onsite", "Malaysia"),
        ("CN; Guangzhou, China; onsite", "China"),
        ("PH; Taguig, Philippines; hybrid", "Philippines"),
        ("Riga, Latvia", "Latvia"),
        ("Bangkok, Thailand; TH; onsite", "Thailand"),
    ],
)
def test_explicit_countries_in_real_feed_locations(location, country):
    group, evidence = location_group(location)
    assert group == "international" and country in evidence


def posting(engine, identity, seen, *, location="Germany", kind="new", changed=None):
    with Session(engine) as session, session.begin():
        employer = add_employer(session, "Employer " + identity)
        employer.created_at = seen
        source = add_source(
            session, employer.id, "ashby", identity, "https://example.test/careers"
        )
        row = Posting(
            source_id=source.id,
            external_posting_id=identity,
            title="Backend Engineer " + identity,
            canonical_job_url="https://jobs.ashbyhq.com/example/" + identity,
            apply_url="https://jobs.ashbyhq.com/example/" + identity + "/application",
            description_text="Develop Python APIs. Two years preferred.",
            locations=location,
            content_hash=identity,
            date_provenance="unknown",
            first_seen_at=seen,
            last_seen_at=max(seen, changed or seen),
            last_changed_at=changed or seen,
            discovery_kind=kind,
            revision=2 if changed else 1,
            status="active",
        )
        session.add(row)
        session.flush()
        return row.id


def smtp_mock(monkeypatch, *, ambiguous=False):
    class SMTP:
        accepted = []
        recipients = []
        tls = False

        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            pass

        def starttls(self, *, context):
            assert context.check_hostname
            type(self).tls = True

        def login(self, username, password):
            assert type(self).tls

        def mail(self, sender):
            return 250, b"OK"

        def rcpt(self, recipient):
            type(self).recipients.append(recipient)
            return 250, b"OK"

        def data(self, body):
            type(self).accepted.append(body)
            if ambiguous:
                raise smtplib.SMTPServerDisconnected("Synthetic lost acknowledgement")
            return 250, b"OK"

        def close(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    config = SMTPConfig(
        "smtp.example.test",
        587,
        "starttls",
        "from@example.test",
        "personal@example.test",
        "synthetic",
        "synthetic",
    )
    return SMTP, config


def test_report_content_distinguishes_baselines_source_dates_and_unknowns(
    database, tmp_path
):
    now = datetime(2027, 4, 1, 14, tzinfo=UTC)
    engine = database[1]
    baseline = posting(
        engine,
        "baseline",
        now - timedelta(days=2),
        location="United States",
        kind="baseline",
    )
    posting(engine, "international", now - timedelta(days=6))
    posting(engine, "uncertain", now - timedelta(days=1), location="Remote")
    posting(engine, "expired", now - timedelta(days=8))
    posting(
        engine, "changed", now - timedelta(days=20), changed=now - timedelta(hours=1)
    )
    published = now - timedelta(days=30)
    with Session(engine) as session, session.begin():
        row = session.get(Posting, baseline)
        row.source_published_at = published
        row.date_provenance = "source:first_published"
    result = generate_reports(engine, tmp_path, now=now, enqueue=False)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert result["count"] == 4
    assert "## US" in text and "## International" in text
    assert "Country unknown or multiple countries" in text
    assert "Initial baseline (not newly published)" in text
    assert f"Source publication: {published.isoformat()}" in text
    assert "Publication date unknown; freshness uncertain" in text
    assert "Materially changed/reappeared" in text
    assert "Backend Engineer expired" not in text
    assert "Apply: https://jobs.ashbyhq.com/example/international/application" in text
    assert "Source excerpt: Two years preferred." in text
    assert "eligibility/sponsorship/start date unverified" in text
    assert "No AI eligibility assessment or ranking" in text
    assert (
        generate_reports(
            engine, tmp_path, now=now + timedelta(hours=10), enqueue=False
        )["count"]
        == 0
    )


def test_injected_report_time_excludes_future_discoveries_and_future_changes(
    database, tmp_path
):
    now = datetime(2027, 4, 1, 14, tzinfo=UTC)
    engine = database[1]
    posting(engine, "boundary", now - timedelta(days=7))
    posting(engine, "future", now + timedelta(minutes=1))
    posting(
        engine,
        "future-change",
        now - timedelta(days=20),
        changed=now + timedelta(minutes=1),
    )
    report = generate_reports(engine, tmp_path, now=now, enqueue=False)
    text = Path(report["path"]).read_text(encoding="utf-8")
    assert report["count"] == 1
    assert "Backend Engineer boundary" in text
    assert "Backend Engineer future" not in text


def test_grouped_new_jobs_email_is_single_personal_message_with_no_baseline_repeat(
    database, tmp_path, monkeypatch
):
    now = datetime(2027, 4, 1, 14, tzinfo=UTC)
    engine = database[1]
    posting(engine, "baseline", now - timedelta(days=1), kind="baseline")
    posting(engine, "new-us", now - timedelta(minutes=3), location="United States")
    posting(engine, "new-intl", now - timedelta(minutes=2), location="Ireland")
    smtp, config = smtp_mock(monkeypatch)
    first = notify_jobs(engine, tmp_path, now=now)
    assert first["email_count"] == 2
    assert deliver_pending(engine, config, now=now)["sent"] == 1
    assert notify_jobs(engine, tmp_path, now=now + timedelta(minutes=5))["count"] == 0
    assert deliver_pending(engine, config, now=now + timedelta(minutes=5))["sent"] == 0
    assert len(smtp.accepted) == 1
    message = BytesParser(policy=policy.default).parsebytes(smtp.accepted[0])
    body = message.get_content()
    assert "Backend Engineer new-us" in body and "Backend Engineer new-intl" in body
    assert "Backend Engineer baseline" not in body
    assert "https://jobs.ashbyhq.com/example/new-intl/application" in body
    assert "unverified" in body
    assert message["To"] == "personal@example.test"
    assert smtp.recipients == ["personal@example.test"]


def test_ambiguous_group_delivery_keeps_local_artifact_and_does_not_resend(
    database, tmp_path, monkeypatch
):
    now = datetime(2027, 4, 1, 14, tzinfo=UTC)
    engine = database[1]
    posting(engine, "new", now - timedelta(minutes=1))
    smtp, config = smtp_mock(monkeypatch, ambiguous=True)
    notification = notify_jobs(engine, tmp_path, now=now)
    assert deliver_pending(engine, config, now=now)["uncertain"] == 1
    assert Path(notification["path"]).is_file()
    assert "Backend Engineer new" in Path(notification["path"]).read_text(
        encoding="utf-8"
    )
    assert deliver_pending(engine, config, now=now + timedelta(days=1))["sent"] == 0
    assert len(smtp.accepted) == 1
    with Session(engine) as session:
        receipts = list(
            session.scalars(select(Delivery).where(Delivery.channel == "smtp_alert"))
        )
        assert len(receipts) == 1 and receipts[0].status == "uncertain"


def test_never_attempted_scheduled_report_backlog_coalesces_without_losing_jobs(
    database, tmp_path, monkeypatch
):
    engine = database[1]
    now = datetime(2027, 4, 1, 14, tzinfo=UTC)
    for day in range(3):
        moment = now + timedelta(days=day)
        posting(engine, f"day-{day}", moment - timedelta(minutes=1))
        result = generate_reports(
            engine,
            tmp_path,
            now=moment,
            slot_key=f"report:{moment.date().isoformat()}:10",
        )
        assert result["email_count"] == day + 1
    smtp, config = smtp_mock(monkeypatch)
    with Session(engine) as session:
        groups = list(
            session.scalars(
                select(TaskRun).where(
                    TaskRun.task_key.startswith("email:nonai-report:")
                )
            )
        )
        assert sorted(row.status for row in groups) == [
            "pending",
            "superseded",
            "superseded",
        ]
        assert (
            len(
                list(
                    session.scalars(
                        select(Delivery).where(Delivery.channel == "smtp_report")
                    )
                )
            )
            == 3
        )
    assert deliver_pending(engine, config, now=now + timedelta(days=2))["sent"] == 1
    assert len(smtp.accepted) == 1
    body = BytesParser(policy=policy.default).parsebytes(smtp.accepted[0]).get_content()
    assert all(f"Backend Engineer day-{day}" in body for day in range(3))
    assert (
        len(list(tmp_path.glob("nonai-report-*.md"))) == 6
    )  # Retain original local/email artifacts.


@pytest.mark.parametrize(
    "location,group",
    [
        ("San Francisco / London", "unknown"),
        ("London, England", "international"),
        ("San Francisco, CA", "us"),
    ],
)
def test_explicit_international_and_mixed_city_geography_is_conservative(
    location, group
):
    assert location_group(location)[0] == group


def test_requirements_excerpts_preserve_years_and_preferences_after_intro_boilerplate():
    description = (
        "We build software. Our developer community grows. Our backend teams care. "
        "Our platform uses Python. Required: 5+ years of backend experience. "
        "Preferred: Java and Docker experience."
    )
    excerpts = requirement_excerpts(description)
    assert "Required: 5+ years of backend experience." in excerpts
    assert "Preferred: Java and Docker experience." in excerpts
    assert all(excerpt in description for excerpt in excerpts)


@pytest.mark.parametrize(
    "title,description,expected",
    [
        ("Talent Acquisition Partner", "We build developer tools.", "unrelated"),
        ("Talent Acquisition Sourcer", "Support a software business.", "unrelated"),
        (
            "Software Engineer, Talent Acquisition Platform",
            "Develop tools.",
            "software evidence",
        ),
        (
            "Talent Acquisition Sourcer",
            "Develop Python tools for candidate data.",
            "software evidence",
        ),
    ],
)
def test_hr_synonyms_do_not_mask_genuine_programming_work(title, description, expected):
    assert assess_relevance(title, description) == expected


@pytest.mark.parametrize(
    "instant,discovery,report",
    [
        ("2027-03-14T09:59:59+00:00", None, None),
        ("2027-03-14T10:00:00+00:00", "discovery:2027-03-14", None),
        ("2027-03-14T13:59:59+00:00", "discovery:2027-03-14", None),
        ("2027-03-14T14:00:00+00:00", "discovery:2027-03-14", "report:2027-03-14:10"),
        ("2027-03-14T23:59:59+00:00", "discovery:2027-03-14", "report:2027-03-14:10"),
        ("2027-03-15T00:00:00+00:00", "discovery:2027-03-14", "report:2027-03-14:20"),
        ("2027-11-07T10:59:59+00:00", None, None),
        ("2027-11-07T11:00:00+00:00", "discovery:2027-11-07", None),
        ("2027-11-07T14:59:59+00:00", "discovery:2027-11-07", None),
        ("2027-11-07T15:00:00+00:00", "discovery:2027-11-07", "report:2027-11-07:10"),
        ("2027-11-08T00:59:59+00:00", "discovery:2027-11-07", "report:2027-11-07:10"),
        ("2027-11-08T01:00:00+00:00", "discovery:2027-11-07", "report:2027-11-07:20"),
    ],
)
def test_exact_scheduler_boundaries_across_both_dst_transitions(
    instant, discovery, report
):
    now = datetime.fromisoformat(instant)
    assert operations.discovery_slot(now) == discovery
    assert operations.report_slot(now) == report
