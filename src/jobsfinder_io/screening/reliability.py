"""Sanitized Gemini error classification and persistent provider backoff.

Provider reset follows Pacific time; the application's independent call budget
continues to use UTC. Never persist messages, response bodies, headers or keys.
"""

import hashlib
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx
from google.genai import errors
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import TaskRun, utc_now


@dataclass(frozen=True)
class Failure:
    category: str
    http_status: int | None = None
    retry_after_seconds: float | None = None
    detail: str | None = None

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "detail" or v is not None}


def _seconds(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= 366 * 86400 else None
    except (TypeError, ValueError):
        return None


def _retry_after(value: str | None, now: datetime) -> float | None:
    numeric = _seconds(value)
    if numeric is not None:
        return numeric
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is not None:
                return _seconds(max(0, (parsed - now).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def classify_error(exc: Exception, *, now: datetime | None = None) -> Failure:
    """Use structured quota metrics/status and private message inspection.

    Ambiguous 429s stay ambiguous. Output contains only fixed category names,
    numeric HTTP status and numeric delay, never provider-supplied free text.
    """
    now = now or utc_now()
    if isinstance(exc, errors.APIError):
        code = exc.code
        body = exc.details if isinstance(exc.details, dict) else {}
        body = body.get("error", body)
        body = body if isinstance(body, dict) else {}
        details = body.get("details", [])
        details = details if isinstance(details, list) else []
        signals = [str(body.get("message", "")), str(body.get("status", ""))]
        delays = []
        response = exc.response
        if response is not None:
            delay = _retry_after(response.headers.get("retry-after"), now)
            if delay is not None:
                delays.append(delay)
        for detail in details:
            if not isinstance(detail, dict):
                continue
            kind = str(detail.get("@type", ""))
            if kind.endswith("RetryInfo"):
                value = detail.get("retryDelay")
                if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?s", value):
                    delay = _seconds(value[:-1])
                    if delay is not None:
                        delays.append(delay)
            if kind.endswith("QuotaFailure"):
                violations = detail.get("violations", [])
                for violation in violations if isinstance(violations, list) else []:
                    if isinstance(violation, dict):
                        signals.extend(
                            str(violation.get(key, ""))
                            for key in ("quotaMetric", "quotaId", "description")
                        )
            if kind.endswith("ErrorInfo"):
                signals.append(str(detail.get("reason", "")))
            if kind.endswith("BadRequest"):
                violations = detail.get("fieldViolations", [])
                for violation in violations if isinstance(violations, list) else []:
                    if isinstance(violation, dict):
                        signals.append(str(violation.get("description", "")))
        delay = max(delays) if delays else None
        signal = " ".join(signals).lower()
        if code == 429:
            if re.search(
                r"credits?.{0,25}(?:depleted|exhausted|insufficient)|"
                r"(?:depleted|insufficient).{0,25}credits?|"
                r"billing.{0,20}(?:disabled|not enabled)|"
                r"spend.{0,15}(?:cap|limit)",
                signal,
            ):
                category = "account_quota_exhausted"
            elif re.search(
                r"per.?day|daily|requestsperday|tokensperday|\brpd\b|\btpd\b",
                signal,
            ):
                category = "daily_quota_exhausted"
            elif re.search(
                r"rate_limit_exceeded|per.?minute|per.?second|requestsperminute|tokensperminute|\brpm\b|\btpm\b",
                signal,
            ):
                category = "rate_limited"
            elif "quota_exceeded" in signal:
                category = "daily_quota_exhausted"
            else:
                category = "quota_or_rate_limit_unknown"
        else:
            category = {
                400: "invalid_request",
                401: "authentication_error",
                403: "permission_error",
                404: "model_unavailable",
                408: "server_timeout",
                500: "server_error",
                502: "server_error",
                503: "server_overload",
                504: "server_timeout",
            }.get(code, "provider_error")
        detail = None
        if code == 400:
            # Fixed diagnostic enums only: never store arbitrary response text,
            # field names, projects, URLs, headers, credentials or input data.
            if re.search(
                r"schema.{0,100}(?:too many states|branching|complex)|constraint.{0,80}too many states",
                signal,
            ):
                detail = "structured_schema_complexity"
            elif "api_key_invalid" in signal or "api key not valid" in signal:
                detail = "invalid_api_key"
            elif "thinking" in signal and re.search(
                r"unsupported|not supported|invalid", signal
            ):
                detail = "unsupported_thinking_configuration"
            elif "schema" in signal:
                detail = "invalid_structured_schema"
            else:
                detail = "unspecified_invalid_argument"
        return Failure(category, code, delay, detail)
    if isinstance(exc, httpx.TimeoutException):
        return Failure("client_timeout")
    if isinstance(exc, httpx.RequestError):
        return Failure("network_error")
    return Failure("client_error")


def control_key(api_key: str, model: str) -> str:
    # A digest separates credentials without retaining their value. Google limits
    # are project-wide: rotating keys is NOT a supported quota workaround.
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    return f"gemini-backoff:{digest}:{model.removeprefix('models/')}"


def provider_block(
    engine: Engine, api_key: str, model: str, *, now: datetime | None = None
) -> dict | None:
    now = now or utc_now()
    with Session(engine) as session:
        record = session.scalar(
            select(TaskRun).where(TaskRun.task_key == control_key(api_key, model))
        )
        if record is None or record.status != "deferred":
            return None
        retry_at = datetime.fromisoformat(record.payload["retry_at"])
        if now >= retry_at:
            return None
        return {
            key: record.payload[key] for key in ("category", "http_status", "retry_at")
        }


def defer_provider(
    engine: Engine,
    api_key: str,
    model: str,
    failure: Failure,
    *,
    now: datetime | None = None,
) -> dict:
    now = now or utc_now()
    key = control_key(api_key, model)
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.task_key == key).values(status=TaskRun.status)
        )
        record = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
        if record is None:
            record = TaskRun(task_key=key, status="deferred", payload={})
            session.add(record)
        failures = min(int(record.payload.get("failures", 0)) + 1, 16)
        category = failure.category
        if category in {"daily_quota_exhausted", "account_quota_exhausted"}:
            pacific = now.astimezone(ZoneInfo("America/Los_Angeles"))
            reset = datetime.combine(
                pacific.date() + timedelta(days=1),
                datetime.min.time(),
                tzinfo=pacific.tzinfo,
            )
            delay = (reset.astimezone(UTC) - now).total_seconds()
        elif category == "quota_or_rate_limit_unknown":
            delay = min(900 * 2 ** (failures - 1), 21600)
        elif category == "rate_limited":
            delay = min(60 * 2 ** (failures - 1), 3600)
        else:
            delay = min(300 * 2 ** (failures - 1), 3600)
        delay = max(delay, failure.retry_after_seconds or 0)
        retry_at = now + timedelta(seconds=delay)
        # Never shorten an existing block due to an overlapping caller.
        previous = record.payload.get("retry_at")
        if record.status == "deferred" and previous:
            retry_at = max(retry_at, datetime.fromisoformat(previous))
        record.status = "deferred"
        record.payload = {
            **failure.payload(),
            "failures": failures,
            "retry_at": retry_at.isoformat(),
        }
        record.completed_at = now
        return {
            key: record.payload[key] for key in ("category", "http_status", "retry_at")
        }


def clear_provider_failure(engine: Engine, api_key: str, model: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun)
            .where(TaskRun.task_key == control_key(api_key, model))
            .values(status="complete", payload={"failures": 0}, completed_at=utc_now())
        )
