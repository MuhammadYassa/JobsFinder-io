"""Actual SDK serialization over mocked HTTP; no live Gemini or employer calls."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import gemini_client
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_screening import output, response, results
from test_screening import posting as posting
from test_screening import profile as profile

from jobsfinder_io.persistence.models import Posting, TaskRun, utc_now
from jobsfinder_io.screening import screen_jobs
from jobsfinder_io.screening.batch import (
    BATCH_PROMPT_VERSION,
    pack_batches,
    screen_batch,
)
from jobsfinder_io.screening.batch_limits import BatchConfig, reserve_request
from jobsfinder_io.screening.queue import refresh_queue
from jobsfinder_io.screening.sessions import screen_due, screening_slot


def add_jobs(engine, posting_id, count, **changes):
    with Session(engine) as session, session.begin():
        base = session.get(Posting, posting_id)
        for i in range(2, count + 1):
            session.add(
                Posting(
                    source_id=base.source_id,
                    external_posting_id=str(i),
                    title=base.title,
                    canonical_job_url=f"https://example.test/jobs/{i}",
                    apply_url=f"https://example.test/jobs/{i}",
                    description_text=base.description_text,
                    content_hash=f"hash{i}",
                    locations="United States",
                    date_provenance="unknown",
                    first_seen_at=utc_now(),
                    last_seen_at=utc_now(),
                    status="active",
                    **changes,
                )
            )


def jobs_from(request):
    body = json.loads(request.content)
    return json.loads(body["contents"][0]["parts"][0]["text"])["jobs"]


def answers(jobs):
    return [
        {
            "job_id": job["job_id"],
            "evaluations": [
                {
                    "pipeline": pipeline,
                    "result": output(
                        evidence=[
                            {
                                "quote": "Build Python services.",
                                "source_url": job["url"],
                            }
                        ]
                    ),
                }
                for pipeline in job["pipelines"]
            ],
        }
        for job in jobs
    ]


def queued(engine):
    with Session(engine) as session:
        return list(
            session.scalars(
                select(TaskRun)
                .where(TaskRun.task_key.startswith("screen-queue:"))
                .order_by(TaskRun.id)
            )
        )


def test_ten_jobs_single_request_validated_stored_and_cached(
    database, posting, profile
):
    add_jobs(database[1], posting, 10)
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["type"] == "array"
        assert body["generationConfig"]["maxOutputTokens"] == 24576
        assert body["generationConfig"]["thinkingConfig"]["thinking_level"] == "LOW"
        assert "contact_email" not in request.content.decode()
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler), attempts=5) as client:
        first = screen_jobs(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
        repeat = screen_jobs(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    assert first["generation_calls"] == 1 and first["screened"] == 10, json.dumps(first)
    assert first["usage"]["total_token_count"] == 25  # once per request, not ten times
    assert repeat["api_calls"] == 0 and repeat["cached"] == 10
    assert len(requests) == 1 and len(results(database[1])) == 10
    assert all(row.status == "complete" for row in queued(database[1]))
    assert all(
        row.prompt_version == BATCH_PROMPT_VERSION for row in results(database[1])
    )


@pytest.mark.parametrize(
    "mode", ["omit", "duplicate", "unknown", "bad_quote", "cross_job_url"]
)
def test_partial_invalid_and_duplicate_ids_stay_queued(
    database, posting, profile, mode
):
    add_jobs(database[1], posting, 3)

    def handler(request):
        rows = answers(jobs_from(request))
        if mode == "omit":
            rows.pop()
        if mode == "duplicate":
            rows[1] = rows[0]
        if mode == "unknown":
            rows[1]["job_id"] = 999999
        if mode == "bad_quote":
            rows[1]["evaluations"][0]["result"]["evidence"][0]["quote"] = (
                "Invented claim"
            )
        if mode == "cross_job_url":
            rows[1]["evaluations"][0]["result"]["evidence"][0]["source_url"] = (
                "https://example.test/jobs/1"
            )
        return httpx.Response(200, json=response(rows))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        result = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
        again = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    expected = {
        "omit": 2,
        "duplicate": 1,
        "unknown": 0,
        "bad_quote": 2,
        "cross_job_url": 2,
    }[mode]
    assert result["screened"] == expected
    assert result["pending"] == 3 - expected
    assert len(results(database[1])) == expected
    assert again["api_calls"] == 0  # invalid items deferred, successful ones cached


def test_each_pipeline_independently_validated_and_saved(database, posting, profile):
    with Session(database[1]) as session, session.begin():
        session.get(Posting, posting).locations = "Remote"
    calls = []

    def handler(request):
        jobs = jobs_from(request)
        calls.append(jobs)
        rows = answers(jobs)
        rows[0]["evaluations"] = rows[0]["evaluations"][:1]
        return httpx.Response(200, json=response(rows))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        result = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    assert result["results"] == 1 and result["pending"] == 1
    assert results(database[1])[0].pipeline == "us"
    assert queued(database[1])[0].status == "pending"


@pytest.mark.parametrize("code", [429, 503, 504])
def test_provider_failure_one_attempt_and_pending_on_restart(
    database, posting, profile, code
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            code,
            json={
                "error": {
                    "code": code,
                    "message": "Requests per day exhausted"
                    if code == 429
                    else "Temporary unavailable",
                }
            },
        )

    with gemini_client(transport=httpx.MockTransport(handler), attempts=5) as client:
        first = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
        again = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    assert len(calls) == first["api_calls"] == 1
    assert again["api_calls"] == 0
    assert queued(database[1])[0].status == "pending"
    assert results(database[1]) == []


def test_packing_10_and_25_output_and_input_bounds(database, posting, profile):
    add_jobs(database[1], posting, 25)
    jobs = refresh_queue(database[1])
    profile_data = json.loads(profile.read_text())
    ten, oversized = pack_batches(jobs, profile_data, BatchConfig())
    assert [len(batch) for batch in ten] == [10, 10, 5] and not oversized
    bigger, _ = pack_batches(
        jobs, profile_data, BatchConfig(max_jobs=25, max_output_tokens=65536)
    )
    assert [len(batch) for batch in bigger] == [25]
    smaller, _ = pack_batches(jobs, profile_data, BatchConfig(max_output_tokens=4096))
    assert all(len(batch) == 1 for batch in smaller)
    huge = {**jobs[0], "description": "Long description " * 30000}
    packed, oversized = pack_batches([huge], profile_data, BatchConfig())
    assert not packed and len(oversized) == 1


def test_oversized_job_never_truncated_or_sent(database, posting, profile, monkeypatch):
    with Session(database[1]) as session, session.begin():
        session.get(Posting, posting).description_text = "software " * 50000
    calls = []
    with gemini_client(
        transport=httpx.MockTransport(lambda request: calls.append(request))
    ) as client:
        result = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    assert result["oversized"] == 1 and not calls
    assert queued(database[1])[0].payload["error"] == "job_exceeds_batch_limits"


def test_token_count_capability_cached_and_accounted(database, posting, profile):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 2400})
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        result = screen_batch(
            database[1],
            profile,
            api_key="fake",
            max_calls=20,
            client=client,
            config=BatchConfig(token_count_mode="always"),
        )
    assert result["screened"] == 1
    assert result["api_calls"] == 2 and result["token_count_calls"] == 1
    assert len(calls) == 2


def test_counted_oversize_splits_on_next_pass_without_generation(
    database, posting, profile
):
    add_jobs(database[1], posting, 2)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"totalTokens": 25000})

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        first = screen_batch(
            database[1],
            profile,
            api_key="fake",
            max_calls=20,
            client=client,
            config=BatchConfig(token_count_mode="always"),
        )
    assert first["generation_calls"] == 0 and first["pending"] == 2
    assert all(row.payload["batch_size_hint"] == 1 for row in queued(database[1]))


def test_pacific_quota_retry_reserve_and_reset_even_same_utc_day(database):
    engine = database[1]
    now = datetime(2027, 3, 14, 7, 10, tzinfo=UTC)  # March13 23:10 PST
    config = BatchConfig(rpm=1000, tpm=1_000_000)
    for _ in range(18):
        assert "request_key" in reserve_request(
            engine, config, now=now, tokens=1, kind="generate"
        )
    assert (
        reserve_request(engine, config, now=now, tokens=1, kind="generate")["reason"]
        == "daily_budget_exhausted"
    )
    for _ in range(2):
        assert "request_key" in reserve_request(
            engine, config, now=now, tokens=1, kind="generate", retry=True
        )
    assert "reason" in reserve_request(
        engine, config, now=now, tokens=1, kind="generate", retry=True
    )
    reset = now.replace(hour=8, minute=0)
    assert "request_key" in reserve_request(
        engine, config, now=reset, tokens=1, kind="generate"
    )


@pytest.mark.parametrize("rpm,tpm,tokens", [(1, 32000, 1), (100, 2000, 1200)])
def test_minute_limits_persist_without_sleep(database, rpm, tpm, tokens):
    config = BatchConfig(rpm=rpm, tpm=tpm)
    now = utc_now()
    assert "request_key" in reserve_request(
        database[1], config, now=now, tokens=tokens, kind="generate"
    )
    assert (
        reserve_request(database[1], config, now=now, tokens=tokens, kind="generate")[
            "reason"
        ]
        == "minute_budget_exhausted"
    )
    assert "request_key" in reserve_request(
        database[1],
        config,
        now=now + timedelta(seconds=61),
        tokens=tokens,
        kind="generate",
    )


@pytest.mark.parametrize(
    "with_profile,with_key,cap", [(False, True, 20), (True, False, 20), (True, True, 0)]
)
def test_missing_configuration_keeps_queue_without_sdk(
    database, posting, profile, monkeypatch, with_profile, with_key, cap
):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled screening constructed a client")

    monkeypatch.setattr("jobsfinder_io.screening.batch.genai.Client", forbidden)
    result = screen_batch(
        database[1],
        profile if with_profile else None,
        api_key="fake" if with_key else None,
        max_calls=cap,
    )
    assert result["api_calls"] == 0 and result["pending"] == 1
    assert queued(database[1])[0].status == "pending"


def test_queue_update_closure_and_successful_cache_invalidation(
    database, posting, profile
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        assert (
            screen_batch(
                database[1], profile, api_key="fake", max_calls=20, client=client
            )["screened"]
            == 1
        )
        with Session(database[1]) as session, session.begin():
            post = session.get(Posting, posting)
            post.content_hash = "materially-changed"
            post.revision += 1
        assert (
            screen_batch(
                database[1], profile, api_key="fake", max_calls=20, client=client
            )["screened"]
            == 1
        )
    assert len(calls) == 2
    assert [row.status for row in queued(database[1])] == ["superseded", "complete"]
    with Session(database[1]) as session, session.begin():
        session.get(Posting, posting).status = "closed"
    assert refresh_queue(database[1]) == []
    assert all(row.status == "superseded" for row in queued(database[1]))


@pytest.mark.parametrize(
    "instant,slot",
    [
        ("2027-03-13T14:29:00+00:00", None),
        ("2027-03-13T14:30:00+00:00", "batch-session:2027-03-13:09:30"),
        ("2027-03-14T13:30:00+00:00", "batch-session:2027-03-14:09:30"),
        ("2027-03-14T14:00:00+00:00", None),
        ("2027-03-14T23:30:00+00:00", "batch-session:2027-03-14:19:30"),
        ("2027-11-07T14:30:00+00:00", "batch-session:2027-11-07:09:30"),
        ("2027-11-08T00:30:00+00:00", "batch-session:2027-11-07:19:30"),
    ],
)
def test_sessions_before_reports_and_dst(instant, slot):
    assert screening_slot(datetime.fromisoformat(instant)) == slot


def test_disabled_and_repeated_scheduled_session(database, posting, profile):
    now = datetime(2027, 4, 1, 13, 30, tzinfo=UTC)
    assert (
        screen_due(database[1], profile, now=now, api_key="fake", max_calls=20)[
            "status"
        ]
        == "disabled"
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        first = screen_due(
            database[1],
            profile,
            now=now,
            enabled=True,
            api_key="fake",
            max_calls=20,
            client=client,
        )
        second = screen_due(
            database[1],
            profile,
            now=now,
            enabled=True,
            api_key="fake",
            max_calls=20,
            client=client,
        )
    assert first["screened"] == 1 and second["status"] == "already_complete"
    assert len(calls) == 1


def test_twenty_five_configured_jobs_complete_in_one_request(
    database, posting, profile
):
    add_jobs(database[1], posting, 25)
    with gemini_client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=response(answers(jobs_from(request)))
            )
        )
    ) as client:
        result = screen_batch(
            database[1],
            profile,
            api_key="fake",
            max_calls=20,
            client=client,
            config=BatchConfig(max_jobs=25, max_output_tokens=65536),
        )
    assert result["screened"] == 25 and result["api_calls"] == 1


def test_profile_change_invalidates_cache(database, posting, profile):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        screen_batch(database[1], profile, api_key="fake", max_calls=20, client=client)
        value = json.loads(profile.read_text())
        value["skills"].append("Java")
        profile.write_text(json.dumps(value))
        result = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    assert result["api_calls"] == 1 and len(calls) == 2
    assert len(results(database[1])) == 2


def test_empty_selection_never_defaults_to_all_jobs(database, posting, profile):
    result = screen_batch(
        database[1], profile, api_key="fake", max_calls=20, posting_ids=[]
    )
    assert result["api_calls"] == 0 and not queued(database[1])


def test_retry_after_overload_survives_restart_and_uses_reserved_request(
    database, posting, profile
):
    engine = database[1]
    now = utc_now()
    config = BatchConfig(rpm=100, tpm=1_000_000)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                503, json={"error": {"code": 503, "message": "Overloaded"}}
            )
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        first = screen_batch(
            engine,
            profile,
            api_key="fake",
            max_calls=20,
            client=client,
            now=now,
            config=config,
        )
        assert first["api_calls"] == 1
        for _ in range(17):
            assert "request_key" in reserve_request(
                engine, config, now=now, tokens=1, kind="generate"
            )
        again = screen_batch(
            engine,
            profile,
            api_key="fake",
            max_calls=20,
            client=client,
            now=now + timedelta(minutes=6),
            config=config,
        )
    assert again["screened"] == 1 and again["api_calls"] == 1
    assert queued(engine)[0].payload["attempts"] == 2
    assert len(calls) == 2


def test_exhausted_daily_budget_issues_no_http(database, posting, profile):
    now = utc_now()
    config = BatchConfig(rpm=100, tpm=1_000_000)
    for _ in range(18):
        reserve_request(database[1], config, now=now, tokens=1, kind="generate")

    def forbidden(request):
        pytest.fail("Exhausted quota must stop before HTTP")

    with gemini_client(transport=httpx.MockTransport(forbidden)) as client:
        result = screen_batch(
            database[1],
            profile,
            api_key="fake",
            max_calls=20,
            client=client,
            config=config,
            now=now,
        )
    assert result["api_calls"] == 0 and result["pending"] == 1
    assert result["limit"]["reason"] == "daily_budget_exhausted"


def test_utc_midnight_does_not_reset_pacific_quota(database):
    config = BatchConfig(rpm=100, tpm=1_000_000)
    now = datetime(2027, 4, 1, 23, 55, tzinfo=UTC)
    for _ in range(18):
        reserve_request(database[1], config, now=now, tokens=1, kind="generate")
    assert "reason" in reserve_request(
        database[1], config, now=now + timedelta(minutes=10), tokens=1, kind="generate"
    )


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY"])
def test_truncated_or_blocked_response_stays_queued_and_preserves_usage(
    database, posting, profile, finish
):
    def handler(request):
        value = response(answers(jobs_from(request)))
        value["candidates"][0]["finishReason"] = finish
        return httpx.Response(200, json=value)

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        result = screen_batch(
            database[1], profile, api_key="fake", max_calls=20, client=client
        )
    assert result["pending"] == 1 and not results(database[1])
    assert result["usage"]["total_token_count"] == 25
    assert queued(database[1])[0].status == "pending"


def test_unknown_sponsorship_preferred_experience_and_flexible_may_start(
    database, posting, profile
):
    with Session(database[1]) as session, session.begin():
        session.get(
            Posting, posting
        ).description_text += " Graduate intake May 2027. Start date is flexible."

    def handler(request):
        job = jobs_from(request)[0]
        value = output(
            disposition="reject",
            start_class="D",
            primary_reason="June availability versus May graduate intake.",
        )
        return httpx.Response(
            200,
            json=response(
                [
                    {
                        "job_id": job["job_id"],
                        "evaluations": [{"pipeline": "us", "result": value}],
                    }
                ]
            ),
        )

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        screen_batch(database[1], profile, api_key="fake", max_calls=20, client=client)
    result = results(database[1])[0].payload
    assert result["disposition"] == "needs_review" and result["start_class"] == "B"
    assert result["visa_class"] == "B" and result["preferred_experience"] == "3 years"


def test_screening_lock_does_not_block_monitoring_and_does_block_other_screeners(
    database, monkeypatch, capsys
):
    from jobsfinder_io.cli import main
    from jobsfinder_io.runlock import database_run_lock

    path = database[0]
    with database_run_lock(path.with_name(path.stem + ".screening.db")):
        assert main(["--db", str(path), "health"]) == 0
        assert main(["--db", str(path), "screen-due"]) == 1
    capsys.readouterr()


@pytest.mark.parametrize(
    "reason",
    [
        "Preferred experience exceeds the candidate background.",
        "Sponsorship status is unknown.",
    ],
)
def test_unknown_visa_or_preferred_experience_cannot_alone_reject(
    database, posting, profile, reason
):
    def handler(request):
        rows = answers(jobs_from(request))
        rows[0]["evaluations"][0]["result"].update(
            disposition="reject", primary_reason=reason
        )
        return httpx.Response(200, json=response(rows))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        screen_batch(database[1], profile, api_key="fake", max_calls=20, client=client)
    assert results(database[1])[0].disposition == "needs_review"


def test_network_wait_holds_no_database_or_monitoring_lock(database, posting, profile):
    from jobsfinder_io.runlock import database_run_lock

    path, engine = database

    def handler(request):
        # Simulate a monitoring worker updating the job during the API wait.
        with database_run_lock(path):
            with Session(engine) as session, session.begin():
                post = session.get(Posting, posting)
                post.revision += 1
                post.content_hash = "changed-during-request"
            refresh_queue(engine)
        return httpx.Response(200, json=response(answers(jobs_from(request))))

    with (
        database_run_lock(path.with_name(path.stem + ".screening.db")),
        gemini_client(transport=httpx.MockTransport(handler)) as client,
    ):
        screen_batch(engine, profile, api_key="fake", max_calls=20, client=client)
    assert [row.status for row in queued(engine)] == ["superseded", "pending"]
    assert results(engine)[0].content_hash == "hash1"  # preserved historical snapshot


def test_compatible_individual_success_cache_is_reused(
    database, posting, profile, monkeypatch
):
    from jobsfinder_io.screening import screen_jobs_individual

    with gemini_client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response(output()))
        )
    ) as client:
        assert (
            screen_jobs_individual(database[1], profile, api_key="fake", client=client)[
                "api_calls"
            ]
            == 2
        )

    def forbidden(*args, **kwargs):
        pytest.fail("Compatible cached results must not call Gemini")

    monkeypatch.setattr("jobsfinder_io.screening.batch.genai.Client", forbidden)
    result = screen_batch(database[1], profile, api_key="fake", max_calls=20)
    assert result["cached"] == 1 and result["api_calls"] == 0
