"""Flash-Lite compatibility and manually labeled synthetic policy regressions."""

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from conftest import gemini_client
from test_batch_screening import add_jobs, answers, jobs_from
from test_screening import output, response
from test_screening import posting as posting
from test_screening import profile as profile

from jobsfinder_io.persistence.models import utc_now
from jobsfinder_io.screening import (
    DEFAULT_MODEL,
    graduation_year_from_profile,
    validate_result,
)
from jobsfinder_io.screening.batch import screen_batch
from jobsfinder_io.screening.batch_limits import (
    BatchConfig,
    load_batch_config,
    reserve_request,
)


def test_flash_lite_quota_environment(monkeypatch):
    for key, value in {
        "GEMINI_DAILY_LIMIT": "500",
        "GEMINI_RPM": "15",
        "GEMINI_TPM": "250000",
    }.items():
        monkeypatch.setenv(key, value)
    config = load_batch_config()
    assert (config.daily_limit, config.rpm, config.tpm) == (500, 15, 250000)
    with pytest.raises(ValueError):
        replace(config, daily_limit=501)


def test_graduation_year_comes_from_education_not_availability():
    assert (
        graduation_year_from_profile(
            {"education": "Synthetic BA; expected graduation May 2027"}
        )
        == 2027
    )
    assert graduation_year_from_profile({"available_from": "2027-06-01"}) is None
    assert (
        graduation_year_from_profile(
            {"education": "graduation May 2027", "facts": ["graduation 2028"]}
        )
        is None
    )


def test_full_daily_allowance_and_retry_reserve(database):
    config = BatchConfig(rpm=1000, tpm=1_000_000)
    now = utc_now()
    for _ in range(498):
        assert "request_key" in reserve_request(
            database[1], config, now=now, tokens=1, kind="generate"
        )
    assert (
        reserve_request(database[1], config, now=now, tokens=1, kind="generate")[
            "reason"
        ]
        == "daily_budget_exhausted"
    )
    for _ in range(2):
        assert "request_key" in reserve_request(
            database[1], config, now=now, tokens=1, kind="generate", retry=True
        )
    assert "reason" in reserve_request(
        database[1], config, now=now, tokens=1, kind="generate", retry=True
    )


def test_fifteen_requests_per_minute(database):
    config, now = BatchConfig(), utc_now()
    for _ in range(15):
        assert "request_key" in reserve_request(
            database[1], config, now=now, tokens=1, kind="generate"
        )
    assert (
        reserve_request(database[1], config, now=now, tokens=1, kind="generate")[
            "reason"
        ]
        == "minute_budget_exhausted"
    )


def test_250000_input_tokens_per_minute(database):
    config, now = BatchConfig(), utc_now()
    for _ in range(2):
        assert "request_key" in reserve_request(
            database[1], config, now=now, tokens=125000, kind="generate"
        )
    assert (
        reserve_request(database[1], config, now=now, tokens=1, kind="generate")[
            "reason"
        ]
        == "minute_budget_exhausted"
    )


def test_flash_lite_structured_batch_one_attempt(database, posting, profile):
    add_jobs(database[1], posting, 5)
    calls = []

    def handler(request):
        calls.append(request)
        assert "gemini-3.5-flash-lite:generateContent" in request.url.path
        cfg = json.loads(request.content)["generationConfig"]
        assert cfg["responseMimeType"] == "application/json"
        assert cfg["responseJsonSchema"]["type"] == "array"
        assert cfg["thinkingConfig"]["thinking_level"] == "LOW"
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler), attempts=5) as client:
        result = screen_batch(
            database[1],
            profile,
            api_key="fake",
            client=client,
            model=DEFAULT_MODEL,
            max_calls=1,
            max_attempts=1,
            config=BatchConfig(token_count_mode="estimate"),
        )
    assert result["screened"] == 5 and result["api_calls"] == 1 and len(calls) == 1


CASES = json.loads(
    (Path(__file__).parent / "fixtures/eligibility_labeled.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_manually_labeled_eligibility_cases(case):
    value = output(
        disposition=case.get("model_disposition", case["expected"]),
        primary_reason=case.get("reason", "Manual synthetic case: " + case["id"]),
        visa_class=case["visa"],
        start_class=case["start"],
        required_experience=case["required"],
        preferred_experience=case["preferred"],
        evidence=[{"quote": case["quote"], "source_url": "https://example.test/job"}],
    )
    result = validate_result(
        value,
        case["text"],
        "https://example.test/job",
        available_from="2027-06-01",
        graduation_year=2027,
    )
    assert result["disposition"] == case["expected"]
    assert result["start_class"] == case.get("expected_start", case["start"])
