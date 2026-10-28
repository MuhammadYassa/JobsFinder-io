"""Durable personal email outbox, with conservative SMTP acknowledgement handling."""

from __future__ import annotations

import contextlib
import hashlib
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid, parseaddr
from uuid import uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import Delivery, TaskRun, utc_now

MAX_ATTEMPTS = 3


def _address(value: str) -> str:
    if any(char in value for char in "\r\n,;"):
        raise ValueError("SMTP addresses must contain one mailbox")
    name, address = parseaddr(value)
    if name or address != value or address.count("@") != 1:
        raise ValueError("SMTP addresses must contain one plain mailbox")
    local, domain = address.split("@")
    if not local or not domain or any(char.isspace() for char in address):
        raise ValueError("Invalid SMTP mailbox")
    try:
        address.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("SMTP mailbox must use ASCII") from None
    return address


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    security: str
    sender: str
    recipient: str
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    timeout: float = 30

    def __post_init__(self) -> None:
        if not self.host or any(char.isspace() for char in self.host):
            raise ValueError("Invalid SMTP_HOST")
        if self.security not in {"starttls", "ssl"}:
            raise ValueError("SMTP_SECURITY must be starttls or ssl")
        if not 1 <= self.port <= 65535 or not 0 < self.timeout <= 120:
            raise ValueError("Invalid SMTP port or timeout")
        _address(self.sender)
        _address(self.recipient)
        if bool(self.username) != bool(self.password):
            raise ValueError("Set both SMTP_USERNAME and SMTP_PASSWORD")


def load_smtp_config() -> SMTPConfig | None:
    """Missing delivery settings leave monitoring and the local outbox operational."""
    names = ("SMTP_HOST", "SMTP_FROM", "SMTP_TO")
    values = [os.getenv(name, "").strip() for name in names]
    if not all(values):
        return None
    security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    try:
        port = int(os.getenv("SMTP_PORT", "465" if security == "ssl" else "587"))
    except ValueError:
        raise ValueError("SMTP_PORT must be an integer") from None
    return SMTPConfig(
        host=values[0],
        port=port,
        security=security,
        sender=values[1],
        recipient=values[2],
        username=os.getenv("SMTP_USERNAME", ""),
        password=os.getenv("SMTP_PASSWORD", ""),
    )


def _write_lock(session: Session) -> None:
    # Acquire SQLite's writer lock before reads, including empty-table races.
    session.execute(update(TaskRun).where(TaskRun.id == -1).values(status="pending"))


def _receipt_query(item: dict):
    return select(Delivery).filter_by(**item)


def enqueue_email(
    engine: Engine, key: str, subject: str, body: str, *, items=(), artifact_path=None
) -> dict:
    """Atomically reserve all receipts and retain content even without credentials."""
    if not key or any(char in subject for char in "\r\n"):
        raise ValueError("Invalid email key or subject")
    normalized = []
    for item in items:
        value = {
            name: item[name]
            for name in ("posting_id", "revision", "pipeline", "channel")
        }
        if value["channel"] not in {"smtp_alert", "smtp_report"}:
            raise ValueError("Invalid SMTP delivery channel")
        if value not in normalized:
            normalized.append(value)
    task_key = "email:" + key
    with Session(engine) as session, session.begin():
        _write_lock(session)
        existing = session.scalar(select(TaskRun).where(TaskRun.task_key == task_key))
        if existing:
            return {
                "key": key,
                "status": existing.status,
                "queued": False,
                "items": len(existing.payload.get("items", [])),
            }
        receipts = [session.scalar(_receipt_query(item)) for item in normalized]
        if any(
            receipt is not None and receipt.status != "superseded"
            for receipt in receipts
        ):
            return {"key": key, "status": "conflict", "queued": False, "items": 0}
        path = str(artifact_path) if artifact_path is not None else None
        for item, receipt in zip(normalized, receipts, strict=True):
            if receipt is None:
                session.add(Delivery(**item, status="pending", artifact_path=path))
            else:
                # A replacement digest reuses the unique per-job reservation;
                # the old group's immutable body/history remains on TaskRun.
                receipt.status = "pending"
                receipt.artifact_path = path
                receipt.sent_at = None
        session.add(
            TaskRun(
                task_key=task_key,
                status="pending",
                payload={
                    "subject": subject,
                    "body": body,
                    "artifact_path": path,
                    "items": normalized,
                    "attempts": 0,
                    "next_attempt_at": None,
                    "message_id": make_msgid(domain="jobsfinder.local"),
                    "history": [],
                },
            )
        )
    return {"key": key, "status": "pending", "queued": True, "items": len(normalized)}


def supersede_unsent_reports(engine: Engine, key: str) -> int:
    """Replace never-attempted old digests before composing a fresh report."""
    return _supersede_unsent_groups(engine, key, "nonai-report:")


def supersede_unsent_alerts(engine: Engine, key: str) -> int:
    """Combine never-attempted old alerts into the current eligible-job group."""
    return _supersede_unsent_groups(engine, key, "nonai-alert:")


def _supersede_unsent_groups(engine: Engine, key: str, prefix: str) -> int:
    """Release reservations only when no SMTP attempt could have occurred.

    Sent, attempted, and uncertain groups retain their reservations. A retry of
    an existing group cannot supersede its own original message snapshot.
    """
    if not key.startswith(prefix):
        raise ValueError("Message replacement requires a matching non-AI group")
    now = utc_now()
    with Session(engine) as session, session.begin():
        _write_lock(session)
        current = "email:" + key
        if (
            session.scalar(select(TaskRun).where(TaskRun.task_key == current))
            is not None
        ):
            return 0
        groups = list(
            session.scalars(
                select(TaskRun).where(
                    TaskRun.task_key.startswith("email:" + prefix),
                    TaskRun.status.in_(["pending", "failed"]),
                )
            )
        )
        superseded = 0
        for group in groups:
            if group.payload.get("attempts", 0) != 0:
                continue
            group.status = "superseded"
            group.completed_at = now
            group.payload = {
                **group.payload,
                "superseded_by": key,
                "retryable": False,
                "next_attempt_at": None,
                "history": [
                    *group.payload.get("history", []),
                    {
                        "at": now.isoformat(),
                        "status": "superseded",
                        "error": "replaced_by_new_group",
                    },
                ],
            }
            _mark_receipts(session, group.payload, "superseded", now)
            superseded += 1
        return superseded


def _send(
    config: SMTPConfig, payload: dict, now: datetime
) -> tuple[str, str | None, bool]:
    """Return safe outcome, safe error code, and whether a confirmed retry is safe."""
    message = EmailMessage(policy=SMTP)
    message["From"] = config.sender
    message["To"] = config.recipient
    message["Subject"] = payload["subject"]
    message["Date"] = format_datetime(now)
    message["Message-ID"] = payload["message_id"]
    message.set_content(payload["body"])
    client = None
    data_started = False
    try:
        context = ssl.create_default_context()
        if config.security == "ssl":
            client = smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout, context=context
            )
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if config.username:
            client.login(config.username, config.password)
        code, _ = client.mail(config.sender)
        if code != 250:
            raise smtplib.SMTPResponseException(code, b"mail rejected")
        code, _ = client.rcpt(config.recipient)
        if code not in {250, 251}:
            raise smtplib.SMTPResponseException(code, b"recipient rejected")
        data_started = True
        code, _ = client.data(message.as_bytes())
        if code != 250:
            raise smtplib.SMTPDataError(code, b"data rejected")
        return "sent", None, False
    except smtplib.SMTPResponseException as error:
        # An explicit rejection confirms nonacceptance, even after DATA.
        return "failed", f"smtp_{error.smtp_code}", 400 <= error.smtp_code < 500
    except (OSError, smtplib.SMTPException) as error:
        return (
            "uncertain" if data_started else "failed",
            type(error).__name__,
            not data_started,
        )
    finally:
        if client is not None:
            # QUIT/disconnect failure cannot reverse acknowledged acceptance.
            with contextlib.suppress(OSError):
                client.close()


def deliver_pending(
    engine: Engine,
    config: SMTPConfig | None,
    *,
    now: datetime | None = None,
    limit: int = 10,
) -> dict:
    """Dispatch bounded queued messages. Ambiguous DATA is never replayed."""
    now = now or utc_now()
    if now.tzinfo is None or limit < 0:
        raise ValueError("Use an aware timestamp and nonnegative email limit")
    result = {
        "sent": 0,
        "failed": 0,
        "uncertain": 0,
        "deferred": 0,
        "missing_config": config is None,
        "outcomes": [],
    }
    with Session(engine) as session, session.begin():
        _write_lock(session)
        # Callers hold the application's process lock. A previous sending claim
        # therefore belongs to an interrupted process, not an active dispatcher.
        rows = session.scalars(
            select(TaskRun).where(TaskRun.task_key.startswith("email:"))
        ).all()
        for row in rows:
            if row.status == "sending":
                row.status = "uncertain"
                row.completed_at = now
                row.payload = {
                    **row.payload,
                    "error": "interrupted_delivery",
                    "next_attempt_at": None,
                }
                _mark_receipts(session, row.payload, "uncertain", now)
                result["uncertain"] += 1
    if config is None:
        return result
    fingerprint = hashlib.sha256(config.recipient.encode()).hexdigest()
    for _ in range(limit):
        with Session(engine) as session, session.begin():
            _write_lock(session)
            rows = session.scalars(
                select(TaskRun)
                .where(
                    TaskRun.task_key.startswith("email:"),
                    TaskRun.status.in_(["pending", "failed"]),
                )
                .order_by(TaskRun.id)
            ).all()
            row = None
            for candidate in rows:
                payload = candidate.payload
                if payload.get("attempts", 0) >= MAX_ATTEMPTS:
                    continue
                if candidate.status == "failed" and not payload.get("retryable", False):
                    continue
                due = payload.get("next_attempt_at")
                if due and datetime.fromisoformat(due) > now:
                    continue
                row = candidate
                break
            if row is None:
                break
            payload = dict(row.payload)
            if payload.get("recipient_hash", fingerprint) != fingerprint:
                row.status = "failed"
                row.completed_at = now
                row.payload = {
                    **payload,
                    "retryable": False,
                    "error": "recipient_changed",
                    "next_attempt_at": None,
                    "history": [
                        *payload.get("history", []),
                        {
                            "at": now.isoformat(),
                            "status": "failed",
                            "error": "recipient_changed",
                        },
                    ],
                }
                _mark_receipts(session, payload, "failed", now)
                result["failed"] += 1
                continue
            payload.update(
                attempts=payload.get("attempts", 0) + 1, recipient_hash=fingerprint
            )
            row.status = "sending"
            row.payload = payload
            task_id = row.id
            key = row.task_key.removeprefix("email:")
        status, error, retryable = _send(config, payload, now)
        with Session(engine) as session, session.begin():
            row = session.get(TaskRun, task_id)
            next_attempt = (
                (
                    now + timedelta(minutes=5 * 2 ** (payload["attempts"] - 1))
                ).isoformat()
                if retryable and payload["attempts"] < MAX_ATTEMPTS
                else None
            )
            history = payload.get("history", []) + [
                {"at": now.isoformat(), "status": status, "error": error}
            ]
            row.status = status
            row.completed_at = now
            row.payload = {
                **payload,
                "error": error,
                "retryable": retryable,
                "next_attempt_at": next_attempt,
                "history": history,
            }
            _mark_receipts(session, payload, status, now)
        result[status] += 1
        result["outcomes"].append({"key": key, "status": status, "error": error})
    with Session(engine) as session:
        result["deferred"] = sum(
            1
            for row in session.scalars(
                select(TaskRun).where(
                    TaskRun.task_key.startswith("email:"), TaskRun.status == "failed"
                )
            )
            if row.payload.get("next_attempt_at")
            and datetime.fromisoformat(row.payload["next_attempt_at"]) > now
        )
    return result


def _mark_receipts(session: Session, payload: dict, status: str, now: datetime) -> None:
    for item in payload.get("items", []):
        receipt = session.scalar(_receipt_query(item))
        if receipt is not None:
            receipt.status = status
            receipt.sent_at = now if status == "sent" else None


def send_test_email(engine: Engine, config: SMTPConfig | None) -> dict:
    """Explicit one-message diagnostic; never drains unrelated queued reports."""
    if config is None:
        return {"status": "missing_config", "sent": 0}
    # Dispatch via an isolated key, while temporarily limiting selection to it.
    key = "test:" + uuid4().hex
    enqueue_email(
        engine,
        key,
        "JobsFinder.io email test",
        "JobsFinder.io can deliver personal job notifications securely.\nNo AI service was used.",
    )
    now = utc_now()
    with Session(engine) as session, session.begin():
        row = session.scalar(select(TaskRun).where(TaskRun.task_key == "email:" + key))
        payload = {
            **row.payload,
            "attempts": 1,
            "recipient_hash": hashlib.sha256(config.recipient.encode()).hexdigest(),
        }
        row.payload = payload
        row.status = "sending"
        task_id = row.id
    status, error, _ = _send(config, payload, now)
    with Session(engine) as session, session.begin():
        row = session.get(TaskRun, task_id)
        row.status = status
        row.completed_at = now
        row.payload = {
            **payload,
            "error": error,
            "retryable": False,
            "history": [{"at": now.isoformat(), "status": status, "error": error}],
        }
    return {"status": status, "sent": int(status == "sent"), "error": error, "key": key}
