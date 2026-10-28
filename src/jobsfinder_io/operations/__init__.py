"""Cron-oriented operations; callers must hold the database process lock.

The CLI owns that lock for the entire invocation. A crash releases the operating
system lock, allowing the next invocation to recover durable running receipts.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from jobsfinder_io.ingestion.polling import poll_source
from jobsfinder_io.persistence.models import (
    Employer,
    JobSource,
    PollRun,
    Posting,
    TaskRun,
    utc_now,
)

LOGGER = logging.getLogger(__name__)


def _time(now: datetime | None) -> datetime:
    value = now or utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Operation time must include timezone")
    return value.astimezone(UTC)


def poll_due(engine: Engine, *, now: datetime | None = None) -> dict:
    """Poll eligible sources with interval/backoff, isolating source failures.

    Caller MUST own database_run_lock. Running polls are then abandoned work
    from a killed process, never another live CLI invocation.
    """
    now = _time(now)
    counts = {"due": 0, "success": 0, "failed": 0, "recovered": 0}
    with Session(engine) as session, session.begin():
        for run in session.scalars(select(PollRun).where(PollRun.status == "running")):
            run.status = "failed"
            run.error_code = "interrupted_process_recovered"
            run.completed_at = max(now, run.started_at)
            counts["recovered"] += 1
        sources = list(
            session.scalars(
                select(JobSource)
                .where(
                    JobSource.status.in_(["validated", "error"]),
                    JobSource.validated_at.is_not(None),
                )
                .order_by(JobSource.id)
            )
        )
        due = []
        for source in sources:
            # Cap the exponent and delay, even if a source is broken for months.
            minutes = min(
                source.poll_interval_minutes * 2 ** min(source.consecutive_failures, 5),
                24 * 60,
            )
            if (
                source.last_attempt_at is None
                or now >= source.last_attempt_at + timedelta(minutes=minutes)
            ):
                due.append(source.id)
    counts["due"] = len(due)
    for source_id in due:
        try:
            result = poll_source(engine, source_id)
            counts["success" if result.status == "complete_success" else "failed"] += 1
        except Exception as exc:
            counts["failed"] += 1
            LOGGER.error(
                json.dumps(
                    {
                        "event": "poll_error",
                        "source_id": source_id,
                        "error": type(exc).__name__,
                    }
                )
            )
    return counts


def _task(engine: Engine, key: str, now: datetime, action) -> dict:
    """Persist success receipts; retry failed/interrupted work on next tick."""
    with Session(engine) as session, session.begin():
        run = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
        if run is not None and run.status == "complete":
            return {"status": "already_complete"}
        if run is None:
            run = TaskRun(task_key=key, status="running", started_at=now)
            session.add(run)
        else:
            run.status = "running"
            run.started_at = now
            run.completed_at = None
        session.flush()
        identity = run.id
    try:
        payload = action()
        state = "complete"
    except Exception as exc:
        payload = {"error": type(exc).__name__}
        state = "failed"
    with Session(engine) as session, session.begin():
        run = session.get(TaskRun, identity)
        run.status = state
        run.completed_at = max(utc_now(), run.started_at)
        run.payload = payload
    return {"status": state, "result": payload}


def report_slot(now: datetime) -> str | None:
    """Latest due slot on this New York calendar day, including DST changes."""
    local = _time(now).astimezone(ZoneInfo("America/New_York"))
    hour = 20 if local.hour >= 20 else 10 if local.hour >= 10 else None
    return f"report:{local.date().isoformat()}:{hour:02d}" if hour else None


def discovery_slot(now: datetime) -> str | None:
    """Daily discovery becomes due at 06:00 New York, with same-day catch-up."""
    local = _time(now).astimezone(ZoneInfo("America/New_York"))
    return f"discovery:{local.date().isoformat()}" if local.hour >= 6 else None


def run_due(
    engine: Engine,
    *,
    profile_path: str | Path | None = None,
    candidates_path: str | Path | None = None,
    output_dir: str | Path = Path("data/reports"),
    api_key: str | None = None,
    preliminary_model: str = "gemini-3.8-flash",
    review_model: str = "gemini-3.8-flash",
    max_calls: int = 0,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
    now: datetime | None = None,
    local_only: bool = False,
) -> dict:
    """One serialized NON-AI tick: discovery, polling, alerts, due reports.

    Run every five minutes via cron. Per-source intervals still govern polling.
    No scheduler is installed and no daemon is started by this function.
    """
    from jobsfinder_io.delivery import deliver_pending, load_smtp_config
    from jobsfinder_io.discovery import discover
    from jobsfinder_io.reporting.non_ai import generate_reports, notify_jobs

    explicit_clock = now is not None
    now = _time(now)
    summary = {}
    discovery_key = discovery_slot(now)
    if candidates_path is not None and discovery_key:
        summary["discovery"] = _task(
            engine,
            discovery_key,
            now,
            lambda: discover(engine, candidates_path, now=now),
        )
    else:
        summary["discovery"] = {
            "status": "not_configured" if candidates_path is None else "not_due"
        }
    summary["polling"] = poll_due(engine, now=now)
    # Include writes from this tick's network work in report metrics. A supplied
    # clock remains fixed for deterministic callers/tests.
    content_now = now if explicit_clock else utc_now()
    # Kept in the signature for callers upgrading from the AI workflow. No SDK,
    # profile, key or model is used by unattended monitoring, even if configured.
    summary["screening"] = {"status": "disabled", "skipped": 1, "api_calls": 0}
    try:
        from jobsfinder_io.screening.queue import refresh_queue

        summary["screening_queue"] = {"candidates": len(refresh_queue(engine))}
    except Exception as exc:
        summary["screening_queue"] = {"error": type(exc).__name__}
    try:
        summary["notifications"] = notify_jobs(
            engine,
            output_dir,
            now=content_now,
            enqueue=not local_only,
        )
    except Exception as exc:
        summary["notifications"] = {"error": type(exc).__name__}
    slot = report_slot(now)
    receipt_key = f"local:{slot}" if local_only and slot else slot
    summary["reports"] = (
        _task(
            engine,
            receipt_key,
            now,
            lambda: generate_reports(
                engine,
                output_dir,
                now=content_now,
                slot_key=receipt_key,
                enqueue=not local_only,
            ),
        )
        if slot
        else {"status": "not_due"}
    )
    try:
        summary["email"] = (
            {"status": "local_only"}
            if local_only
            else deliver_pending(engine, load_smtp_config(), now=content_now)
        )
    except Exception as exc:
        summary["email"] = {"error": type(exc).__name__}
    LOGGER.info(
        json.dumps({"event": "run_due", "at": now.isoformat(), **summary}, default=str)
    )
    return summary


def health(engine: Engine) -> dict:
    """Local health and real registry counts; no network side effects."""
    now = utc_now()
    with Session(engine) as session:
        sources = list(session.scalars(select(JobSource).order_by(JobSource.id)))
        counts = {
            "employers": session.scalar(select(func.count()).select_from(Employer)),
            "sources": len(sources),
            "postings": session.scalar(select(func.count()).select_from(Posting)),
            "active_postings": session.scalar(
                select(func.count())
                .select_from(Posting)
                .where(Posting.status == "active")
            ),
            "running_polls": session.scalar(
                select(func.count())
                .select_from(PollRun)
                .where(PollRun.status == "running")
            ),
        }
        counts["source_health"] = [
            {
                "id": source.id,
                "provider": source.provider,
                "status": source.status,
                "consecutive_failures": source.consecutive_failures,
                "last_success_at": source.last_success_at.isoformat()
                if source.last_success_at
                else None,
                "stale": source.validated_at is not None
                and (
                    source.last_success_at is None
                    or now - source.last_success_at > timedelta(hours=24)
                ),
            }
            for source in sources
        ]
        counts["failed_tasks"] = [
            {"task_key": task.task_key, "error": task.payload.get("error")}
            for task in session.scalars(
                select(TaskRun).where(TaskRun.status == "failed")
            )
        ]
        outbox = list(
            session.scalars(select(TaskRun).where(TaskRun.task_key.like("email:%")))
        )
        counts["email_outbox"] = {
            state: sum(task.status == state for task in outbox)
            for state in ("pending", "sending", "sent", "failed", "uncertain")
        }
        counts["email_review"] = [
            {
                "task_key": task.task_key,
                "status": task.status,
                "error": task.payload.get("error"),
                "attempts": task.payload.get("attempts", 0),
            }
            for task in outbox
            if task.status in {"failed", "uncertain"}
        ]
        counts["screening_queue"] = dict(
            session.execute(
                select(TaskRun.status, func.count())
                .where(TaskRun.task_key.startswith("screen-queue:"))
                .group_by(TaskRun.status)
            ).all()
        )
        counts["batch_budgets"] = [
            {
                "pacific_day": row.task_key.rsplit(":", 1)[-1],
                "requests": row.payload.get("calls", 0),
            }
            for row in session.scalars(
                select(TaskRun).where(
                    TaskRun.task_key.startswith("gemini-batch-budget:")
                )
            )
        ]
        counts["provider_backoffs"] = [
            {
                "model": task.task_key.rsplit(":", 1)[-1],
                "category": task.payload.get("category"),
                "http_status": task.payload.get("http_status"),
                "retry_at": task.payload.get("retry_at"),
            }
            for task in session.scalars(
                select(TaskRun).where(
                    TaskRun.status == "deferred",
                    TaskRun.task_key.like("gemini-backoff:%"),
                )
            )
            if datetime.fromisoformat(task.payload["retry_at"]) > now
        ]
    return counts
