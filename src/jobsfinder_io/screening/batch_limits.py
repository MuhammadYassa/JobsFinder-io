"""Atomic Pacific-day and rolling-minute reservations for every batch API call."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import TaskRun


@dataclass(frozen=True)
class BatchConfig:
    max_jobs: int = 10
    max_input_tokens: int = 24000
    max_output_tokens: int = 24576
    output_tokens_per_job: int = 1600
    output_headroom: int = 1024
    token_count_mode: str = "near_limit"
    daily_limit: int = 500
    retry_reserve: int = 2
    rpm: int = 15
    tpm: int = 250000
    max_batches: int = 8
    timeout_ms: int = 90000

    def __post_init__(self) -> None:
        integers = (
            self.max_jobs,
            self.max_input_tokens,
            self.max_output_tokens,
            self.output_tokens_per_job,
            self.output_headroom,
            self.daily_limit,
            self.retry_reserve,
            self.rpm,
            self.tpm,
            self.max_batches,
            self.timeout_ms,
        )
        if any(type(value) is not int for value in integers):
            raise ValueError("Batch limits must be integers")
        if not (
            1 <= self.max_jobs <= 25
            and 1 <= self.daily_limit <= 500
            and 0 <= self.retry_reserve < self.daily_limit
            and 1 <= self.rpm <= 1000
            and self.tpm > 0
            and 1 <= self.max_input_tokens <= 1_000_000
            and 1024 <= self.max_output_tokens <= 65536
            and self.output_tokens_per_job >= 256
            and self.output_headroom >= 256
            and self.output_headroom + self.output_tokens_per_job
            <= self.max_output_tokens
            and 1 <= self.max_batches <= 20
            and 1000 <= self.timeout_ms <= 180000
        ):
            raise ValueError("Invalid batch limits")
        if self.token_count_mode not in {"estimate", "near_limit", "always"}:
            raise ValueError("Invalid token count mode")


def load_batch_config() -> BatchConfig:
    """Environment configuration without credentials or hidden network calls."""
    names = {
        "max_jobs": "GEMINI_BATCH_SIZE",
        "max_input_tokens": "GEMINI_BATCH_INPUT_TOKENS",
        "max_output_tokens": "GEMINI_BATCH_OUTPUT_TOKENS",
        "output_tokens_per_job": "GEMINI_BATCH_JOB_OUTPUT_TOKENS",
        "daily_limit": "GEMINI_DAILY_LIMIT",
        "retry_reserve": "GEMINI_RETRY_RESERVE",
        "rpm": "GEMINI_RPM",
        "tpm": "GEMINI_TPM",
        "max_batches": "GEMINI_SESSION_BATCHES",
    }
    values = {
        field: int(os.environ[name]) for field, name in names.items() if os.getenv(name)
    }
    if os.getenv("GEMINI_TOKEN_COUNT_MODE"):
        values["token_count_mode"] = os.environ["GEMINI_TOKEN_COUNT_MODE"]
    return BatchConfig(**values)


def reserve_request(
    engine: Engine,
    config: BatchConfig,
    *,
    now: datetime,
    tokens: int,
    kind: str,
    retry: bool = False,
    application_daily_limit: int = 500,
) -> dict:
    """Reserve before I/O; failures/count_tokens consume quota too.

    Limits are application-wide on this database, not per API key. Provider
    backoff additionally handles other applications sharing the Google project.
    """
    pacific = now.astimezone(ZoneInfo("America/Los_Angeles"))
    reset = datetime.combine(
        pacific.date() + timedelta(days=1), datetime.min.time(), tzinfo=pacific.tzinfo
    ).astimezone(UTC)
    key = f"gemini-batch-budget:{pacific.date().isoformat()}"
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.id == -1).values(status="pending")
        )
        budget = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
        if budget is None:
            budget = TaskRun(task_key=key, status="complete", payload={"calls": 0})
            session.add(budget)
        calls = budget.payload.get("calls", 0)
        allowance = min(
            application_daily_limit,
            config.daily_limit if retry else config.daily_limit - config.retry_reserve,
        )
        if calls >= allowance:
            return {"reason": "daily_budget_exhausted", "retry_at": reset.isoformat()}
        utc_key = f"ai-budget:{now.astimezone(UTC).date().isoformat()}"
        utc_budget = session.scalar(select(TaskRun).where(TaskRun.task_key == utc_key))
        if utc_budget is None:
            utc_budget = TaskRun(
                task_key=utc_key, status="complete", payload={"calls": 0}
            )
            session.add(utc_budget)
        recent = list(
            session.scalars(
                select(TaskRun).where(
                    TaskRun.task_key.startswith("gemini-batch-request:"),
                    TaskRun.started_at > now - timedelta(minutes=1),
                )
            )
        )
        if (
            len(recent) >= config.rpm
            or tokens + sum(row.payload["input_tokens"] for row in recent) > config.tpm
        ):
            retry_at = min((row.started_at for row in recent), default=now) + timedelta(
                seconds=61
            )
            return {
                "reason": "minute_budget_exhausted",
                "retry_at": retry_at.isoformat(),
            }
        budget.payload = {"calls": calls + 1}
        utc_budget.payload = {"calls": utc_budget.payload.get("calls", 0) + 1}
        request_key = f"gemini-batch-request:{uuid4().hex}"
        session.add(
            TaskRun(
                task_key=request_key,
                status="reserved",
                started_at=now,
                payload={"kind": kind, "input_tokens": tokens, "retry": retry},
            )
        )
        return {"request_key": request_key}


def record_request(
    engine: Engine, key: str, *, status: str, usage: dict, error=None
) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.id == -1).values(status="pending")
        )
        row = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
        row.status = status
        row.payload = {**row.payload, "usage": usage, "error": error}
        row.completed_at = max(datetime.now(UTC), row.started_at)
