"""Opt-in sessions run independently from hourly monitoring and delivery."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import TaskRun, utc_now
from jobsfinder_io.screening.batch import screen_batch
from jobsfinder_io.screening.queue import refresh_queue


def screening_slot(now: datetime) -> str | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(ZoneInfo("America/New_York"))
    if local.hour not in {9, 19} or local.minute < 30:
        return None
    return f"batch-session:{local.date().isoformat()}:{local.hour:02d}:30"


def screen_due(
    engine: Engine, profile_path=None, *, enabled=False, now=None, **kwargs
) -> dict:
    """Call under the separate screening lock. Failures never affect run-due."""
    supplied_now = now
    now = now or utc_now()
    slot = screening_slot(now)
    if not enabled:
        jobs = refresh_queue(engine)
        return {"status": "disabled", "api_calls": 0, "queued_candidates": len(jobs)}
    if not slot:
        return {"status": "not_due", "api_calls": 0}
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.id == -1).values(status="pending")
        )
        record = session.scalar(select(TaskRun).where(TaskRun.task_key == slot))
        if record is not None and record.status == "complete":
            return {"status": "already_complete", "api_calls": 0}
        if record is None:
            record = TaskRun(
                task_key=slot, status="pending", started_at=now.astimezone(UTC)
            )
            session.add(record)
        identity = slot
    try:
        local = now.astimezone(ZoneInfo("America/New_York"))
        deadline = local.replace(hour=local.hour + 1, minute=0, second=0, microsecond=0)
        result = screen_batch(
            engine,
            profile_path,
            now=supplied_now,
            deadline=deadline.astimezone(UTC),
            **kwargs,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "error": type(exc).__name__,
            "api_calls": 0,
            "pending": 1,
        }
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.id == -1).values(status="pending")
        )
        record = session.scalar(select(TaskRun).where(TaskRun.task_key == identity))
        record.status = "complete" if result.get("pending") == 0 else "pending"
        record.completed_at = utc_now() if record.status == "complete" else None
        record.payload = result
    return result
