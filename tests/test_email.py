import smtplib
import ssl
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io.delivery import (
    SMTPConfig,
    deliver_pending,
    enqueue_email,
    load_smtp_config,
    send_test_email,
)
from jobsfinder_io.persistence.models import Delivery, Posting, TaskRun, utc_now
from jobsfinder_io.registry import add_employer, add_source


@pytest.fixture
def config():
    return SMTPConfig(
        "smtp.example.test",
        587,
        "starttls",
        "from@example.test",
        "personal@example.test",
        "private-user",
        "private-password",
    )


@pytest.fixture
def smtp(monkeypatch):
    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            self.calls = [("connect", args, kwargs)]
            self.failure = None
            self.rcpt_code = 250
            self.data_code = 250

        def ehlo(self):
            self.calls.append(("ehlo",))

        def starttls(self, *, context):
            assert context.check_hostname
            assert context.verify_mode == ssl.CERT_REQUIRED
            self.calls.append(("starttls",))

        def login(self, username, password):
            self.calls.append(("login", username, password))
            if self.failure == "auth":
                raise smtplib.SMTPAuthenticationError(535, b"private-password")

        def mail(self, sender):
            self.calls.append(("mail", sender))
            if self.failure == "mail":
                raise TimeoutError("private-password")
            return 250, b"OK"

        def rcpt(self, recipient):
            self.calls.append(("rcpt", recipient))
            return self.rcpt_code, b"OK"

        def data(self, message):
            self.calls.append(("data", message))
            if self.failure == "data":
                raise smtplib.SMTPServerDisconnected("private-password")
            return self.data_code, b"OK"

        def close(self):
            self.calls.append(("close",))

    instance = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: instance)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: instance)
    return instance


def item(engine):
    now = utc_now()
    with Session(engine) as session, session.begin():
        employer = add_employer(session, "Synthetic employer")
        source = add_source(
            session,
            employer.id,
            "greenhouse",
            "synthetic",
            "https://example.test/careers",
        )
        posting = Posting(
            source_id=source.id,
            external_posting_id="1",
            title="Software Engineer",
            canonical_job_url="https://example.test/1",
            apply_url="https://example.test/apply/1",
            description_text="Python services",
            date_provenance="unknown",
            first_seen_at=now,
            last_seen_at=now,
            content_hash="synthetic",
        )
        session.add(posting)
        session.flush()
        return {
            "posting_id": posting.id,
            "revision": 1,
            "pipeline": "us",
            "channel": "smtp_alert",
        }


def test_config_missing_and_secure_validation(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_FROM", "SMTP_TO"):
        monkeypatch.delenv(name, raising=False)
    assert load_smtp_config() is None
    for name, value in {
        "SMTP_HOST": "smtp.example.test",
        "SMTP_FROM": "from@example.test",
        "SMTP_TO": "personal@example.test",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert load_smtp_config().port == 587
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.delenv("SMTP_PORT", raising=False)
    assert load_smtp_config().port == 465
    monkeypatch.setenv("SMTP_SECURITY", "none")
    with pytest.raises(ValueError, match="SMTP_SECURITY"):
        load_smtp_config()
    with pytest.raises(ValueError):
        SMTPConfig(
            "host",
            587,
            "starttls",
            "from@example.test",
            "a@example.test,b@example.test",
        )


def test_group_receipts_tls_body_and_idempotency(database, config, smtp):
    engine = database[1]
    receipt = item(engine)
    assert enqueue_email(
        engine,
        "alert",
        "New engineering roles",
        "Software Engineer — Python\nhttps://example.test/apply/1",
        items=[receipt],
        artifact_path="local.md",
    )["queued"]
    assert not enqueue_email(engine, "alert", "same", "same", items=[receipt])["queued"]
    assert (
        enqueue_email(engine, "other", "same", "same", items=[receipt])["status"]
        == "conflict"
    )
    assert deliver_pending(engine, config)["sent"] == 1
    assert deliver_pending(engine, config)["sent"] == 0
    actions = [call[0] for call in smtp.calls]
    assert actions.index("starttls") < actions.index("login") < actions.index("data")
    assert [call for call in smtp.calls if call[0] == "rcpt"] == [
        ("rcpt", config.recipient)
    ]
    wire = next(call[1] for call in smtp.calls if call[0] == "data")
    message = BytesParser(policy=policy.default).parsebytes(wire)
    assert "Python" in message.get_content()
    assert message["To"] == config.recipient
    with Session(engine) as session:
        delivery = session.scalar(select(Delivery))
        assert delivery.status == "sent" and delivery.sent_at
        assert session.scalar(select(func.count()).select_from(Delivery)) == 1


def test_missing_config_keeps_local_payload(database):
    engine = database[1]
    enqueue_email(engine, "local", "subject", "body", artifact_path="report.md")
    assert deliver_pending(engine, None)["missing_config"]
    with Session(engine) as session:
        row = session.scalar(select(TaskRun))
        assert row.status == "pending"
        assert row.payload["body"] == "body"
        assert row.payload["artifact_path"] == "report.md"
        assert row.payload["attempts"] == 0


def test_pre_data_timeout_is_deferred_bounded_and_private(database, config, smtp):
    engine = database[1]
    enqueue_email(engine, "retry", "subject", "body")
    smtp.failure = "mail"
    now = utc_now()
    assert deliver_pending(engine, config, now=now)["failed"] == 1
    assert deliver_pending(engine, config, now=now)["failed"] == 0
    assert (
        deliver_pending(engine, config, now=now + timedelta(minutes=5))["failed"] == 1
    )
    assert (
        deliver_pending(engine, config, now=now + timedelta(minutes=15))["failed"] == 1
    )
    assert deliver_pending(engine, config, now=now + timedelta(days=1))["failed"] == 0
    with Session(engine) as session:
        row = session.scalar(select(TaskRun))
        assert row.payload["attempts"] == 3
        assert len(row.payload["history"]) == 3
        assert "private-password" not in str(row.payload)
        assert "private-password" not in repr(config)


@pytest.mark.parametrize("failure", ["auth", "data"])
def test_permanent_or_uncertain_failures_are_never_replayed(
    database, config, smtp, failure
):
    engine = database[1]
    enqueue_email(engine, "failure", "subject", "body")
    smtp.failure = failure
    result = deliver_pending(engine, config)
    assert result["uncertain" if failure == "data" else "failed"] == 1
    smtp.failure = None
    assert (
        deliver_pending(engine, config, now=utc_now() + timedelta(days=1))["sent"] == 0
    )


def test_explicit_data_rejection_retries_without_duplicate_receipts(
    database, config, smtp
):
    engine = database[1]
    receipt = item(engine)
    enqueue_email(engine, "retry", "subject", "body", items=[receipt])
    smtp.data_code = 451
    now = utc_now()
    assert deliver_pending(engine, config, now=now)["failed"] == 1
    smtp.data_code = 250
    assert deliver_pending(engine, config, now=now + timedelta(minutes=5))["sent"] == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Delivery)) == 1
        assert session.scalar(select(Delivery)).status == "sent"


def test_interrupted_sending_requires_review(database, config, smtp):
    engine = database[1]
    receipt = item(engine)
    enqueue_email(engine, "crash", "subject", "body", items=[receipt])
    with Session(engine) as session, session.begin():
        session.scalar(select(TaskRun)).status = "sending"
    assert deliver_pending(engine, config)["uncertain"] == 1
    assert not any(call[0] == "data" for call in smtp.calls)
    with Session(engine) as session:
        assert session.scalar(select(Delivery)).status == "uncertain"


def test_test_email_does_not_drain_other_queue(database, config, smtp):
    engine = database[1]
    enqueue_email(engine, "other", "other", "body")
    assert send_test_email(engine, config)["sent"] == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(TaskRun).where(TaskRun.task_key == "email:other")
            ).status
            == "pending"
        )
    assert len([call for call in smtp.calls if call[0] == "data"]) == 1


def test_ssl_uses_verified_context(database, monkeypatch, smtp):
    calls = []

    def connect(*args, **kwargs):
        calls.append(kwargs)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", connect)
    config = SMTPConfig(
        "host", 465, "ssl", "from@example.test", "personal@example.test"
    )
    enqueue_email(database[1], "ssl", "subject", "body")
    assert deliver_pending(database[1], config)["sent"] == 1
    assert calls[0]["context"].check_hostname
    assert calls[0]["context"].verify_mode == ssl.CERT_REQUIRED
    assert not any(call[0] == "starttls" for call in smtp.calls)


def test_missing_starttls_cannot_fall_back_to_plaintext(
    database, config, smtp, monkeypatch
):
    def unsupported(**kwargs):
        raise smtplib.SMTPNotSupportedError("STARTTLS unavailable")

    monkeypatch.setattr(smtp, "starttls", unsupported)
    enqueue_email(database[1], "tls", "subject", "body")
    assert deliver_pending(database[1], config)["failed"] == 1
    assert not any(call[0] in {"login", "mail", "data"} for call in smtp.calls)


def test_changed_recipient_cannot_reroute_retry(database, config, smtp):
    engine = database[1]
    enqueue_email(engine, "recipient", "subject", "body")
    smtp.failure = "mail"
    now = utc_now()
    assert deliver_pending(engine, config, now=now)["deferred"] == 1
    changed = SMTPConfig(
        "host", 587, "starttls", "from@example.test", "other@example.test"
    )
    smtp.failure = None
    assert deliver_pending(engine, changed, now=now + timedelta(days=1))["failed"] == 1
    assert not any(call[0] == "data" for call in smtp.calls)
