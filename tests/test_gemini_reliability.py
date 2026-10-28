import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from conftest import gemini_client
from google.genai import errors
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_screening import output, response, results
from test_screening import posting as posting
from test_screening import profile as profile

from jobsfinder_io.operations import health
from jobsfinder_io.persistence.models import Posting, ScreeningResult, TaskRun
from jobsfinder_io.screening import DEFAULT_MODEL
from jobsfinder_io.screening import screen_jobs_individual as screen_jobs
from jobsfinder_io.screening.reliability import (
    Failure,
    classify_error,
    clear_provider_failure,
    defer_provider,
    provider_block,
)


def api_error(code, message="temporary", *, details=None, headers=None):
    body = {
        "error": {
            "code": code,
            "message": message,
            "status": "RESOURCE_EXHAUSTED" if code == 429 else "UNAVAILABLE",
            "details": details or [],
        }
    }
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test")
    return errors.APIError(
        code, body, httpx.Response(code, json=body, headers=headers, request=request)
    )


@pytest.mark.parametrize(
    "code,message,expected",
    [
        (429, "Requests per day exhausted", "daily_quota_exhausted"),
        (429, "Per-minute requests exceeded", "rate_limited"),
        (429, "Resource exhausted", "quota_or_rate_limit_unknown"),
        (429, "Prepay credits depleted", "account_quota_exhausted"),
        (429, "Project spend cap exceeded", "account_quota_exhausted"),
        (503, "overloaded", "server_overload"),
        (504, "deadline", "server_timeout"),
        (500, "server error", "server_error"),
        (401, "invalid key", "authentication_error"),
        (404, "model absent", "model_unavailable"),
    ],
)
def test_error_categories_are_distinct_and_sanitized(code, message, expected):
    failure = classify_error(api_error(code, message + " private-secret-marker"))
    assert failure.category == expected
    assert "private-secret-marker" not in json.dumps(failure.payload())


def test_structured_daily_metric_wins_over_short_retry_hint():
    error = api_error(
        429,
        details=[
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [
                    {
                        "quotaMetric": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                        "quotaDimensions": {"project": "private-project"},
                    }
                ],
            },
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2.5s"},
        ],
        headers={"Retry-After": "1"},
    )
    result = classify_error(error)
    assert result.category == "daily_quota_exhausted"
    assert result.retry_after_seconds == 2.5
    assert "private-project" not in json.dumps(result.payload())


def test_generic_billing_advice_does_not_override_explicit_minute_metric():
    error = api_error(
        429,
        "Quota exceeded; check your plan and billing details",
        details=[
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": "GenerateRequestsPerMinutePerProject"}],
            }
        ],
    )
    assert classify_error(error).category == "rate_limited"


def test_retry_after_http_date_and_retryinfo_use_longest_delay():
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    error = api_error(
        503,
        headers={
            "Retry-After": format_datetime(now + timedelta(seconds=90), usegmt=True)
        },
        details=[
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "120s"}
        ],
    )
    assert classify_error(error, now=now).retry_after_seconds == 120


@pytest.mark.parametrize("value", ["invalid", "-1", "NaN", "Infinity"])
def test_malformed_delay_is_ignored(value):
    assert (
        classify_error(
            api_error(503, headers={"Retry-After": value})
        ).retry_after_seconds
        is None
    )


def test_network_client_and_server_timeouts_are_distinguished():
    assert classify_error(httpx.ReadTimeout("secret")).category == "client_timeout"
    assert classify_error(httpx.ConnectError("secret")).category == "network_error"
    assert classify_error(AttributeError("secret")).category == "client_error"
    assert classify_error(api_error(504)).category == "server_timeout"


@pytest.mark.parametrize(
    "now,reset",
    [
        (datetime(2026, 10, 27, 22, tzinfo=UTC), datetime(2026, 10, 28, 7, tzinfo=UTC)),
        (datetime(2026, 11, 1, 20, tzinfo=UTC), datetime(2026, 11, 2, 8, tzinfo=UTC)),
    ],
)
def test_daily_quota_persists_until_pacific_reset(database, now, reset):
    engine = database[1]
    state = defer_provider(
        engine,
        "private-api-key",
        DEFAULT_MODEL,
        Failure("daily_quota_exhausted", 429, 2),
        now=now,
    )
    assert datetime.fromisoformat(state["retry_at"]) == reset
    assert provider_block(
        engine, "private-api-key", DEFAULT_MODEL, now=reset - timedelta(seconds=1)
    )
    assert provider_block(engine, "private-api-key", DEFAULT_MODEL, now=reset) is None
    with Session(engine) as session:
        row = session.scalar(select(TaskRun))
        assert "private-api-key" not in row.task_key + json.dumps(row.payload)


def test_unknown_quota_persists_exponential_backoff(database):
    engine = database[1]
    now = datetime(2026, 10, 27, 22, tzinfo=UTC)
    first = defer_provider(
        engine,
        "key",
        DEFAULT_MODEL,
        Failure("quota_or_rate_limit_unknown", 429),
        now=now,
    )
    assert datetime.fromisoformat(first["retry_at"]) == now + timedelta(minutes=15)
    second = defer_provider(
        engine,
        "key",
        DEFAULT_MODEL,
        Failure("quota_or_rate_limit_unknown", 429),
        now=now + timedelta(minutes=16),
    )
    assert datetime.fromisoformat(second["retry_at"]) == now + timedelta(minutes=46)
    clear_provider_failure(engine, "key", DEFAULT_MODEL)
    assert provider_block(engine, "key", DEFAULT_MODEL, now=now) is None


def test_health_exposes_backoff_without_credential_fingerprint(database):
    defer_provider(
        database[1], "private-key", DEFAULT_MODEL, Failure("daily_quota_exhausted", 429)
    )
    status = health(database[1])["provider_backoffs"]
    assert len(status) == 1 and status[0]["category"] == "daily_quota_exhausted"
    assert status[0]["model"] == DEFAULT_MODEL
    assert "private-key" not in json.dumps(status)
    assert "gemini-backoff:" not in json.dumps(status)


def test_quota_blocks_other_policies_and_future_invocations(database, posting, profile):
    requests = []
    with Session(database[1]) as session, session.begin():
        session.get(Posting, posting).locations = "Worldwide remote"

    def handler(request):
        requests.append(request)
        return httpx.Response(
            429,
            json={"error": {"code": 429, "message": "Requests per day quota exceeded"}},
        )

    with gemini_client(transport=httpx.MockTransport(handler), attempts=5) as client:
        first = screen_jobs(database[1], profile, api_key="fake", client=client)
        with Session(database[1]) as session:
            before = len(list(session.scalars(select(ScreeningResult))))
        second = screen_jobs(database[1], profile, api_key="fake", client=client)
    assert len(requests) == first["api_calls"] == 1
    assert second["api_calls"] == 0 and second["needs_review"] == 2
    assert {row.disposition for row in results(database[1])} == {"needs_review"}
    assert all(row.payload["deferred"] for row in results(database[1]))
    with Session(database[1]) as session:
        assert len(list(session.scalars(select(ScreeningResult)))) == before


def test_no_retries_makes_one_attempt_and_defers_overload(database, posting, profile):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"code": 503, "message": "busy"}})

    with gemini_client(transport=httpx.MockTransport(handler), attempts=5) as client:
        first = screen_jobs(
            database[1], profile, api_key="fake", client=client, max_attempts=1
        )
        second = screen_jobs(
            database[1], profile, api_key="fake", client=client, max_attempts=1
        )
    assert len(requests) == first["api_calls"] == 1 and second["api_calls"] == 0
    assert (
        results(database[1])[-1].payload["provider_failure"]["category"]
        == "server_overload"
    )


def test_long_provider_delay_is_deferred_not_shortened(
    database, posting, profile, monkeypatch
):
    def forbidden(delay):
        pytest.fail("Long Retry-After should defer, not block this command")

    monkeypatch.setattr("jobsfinder_io.screening.time.sleep", forbidden)
    now = datetime.now(UTC)
    with gemini_client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                headers={"Retry-After": "900"},
                json={"error": {"code": 503, "message": "busy"}},
            )
        )
    ) as client:
        result = screen_jobs(database[1], profile, api_key="fake", client=client)
    assert result["api_calls"] == 1
    block = provider_block(database[1], "fake", DEFAULT_MODEL)
    assert datetime.fromisoformat(block["retry_at"]) >= now + timedelta(seconds=900)


def test_expired_failure_is_retried_and_success_clears_backoff(
    database, posting, profile
):
    defer_provider(
        database[1],
        "fake",
        DEFAULT_MODEL,
        Failure("server_overload", 503),
        now=datetime(2000, 1, 1, tzinfo=UTC),
    )
    with gemini_client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response(output()))
        )
    ) as client:
        result = screen_jobs(
            database[1], profile, api_key="fake", client=client, max_attempts=1
        )
    assert (
        result["api_calls"] == 2 and results(database[1])[-1].disposition == "recommend"
    )
    assert provider_block(database[1], "fake", DEFAULT_MODEL) is None
