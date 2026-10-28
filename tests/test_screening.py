import json

import httpx
import pytest
from conftest import gemini_client
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import Posting, ScreeningResult, TaskRun, utc_now
from jobsfinder_io.registry import add_employer, add_source
from jobsfinder_io.screening import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    deterministic_result,
    load_profile,
    pipelines_for,
    validate_result,
)
from jobsfinder_io.screening import (
    screen_jobs_individual as screen_jobs,
)


def test_selected_postings_never_screen_other_active_jobs(database, posting, profile):
    with Session(database[1]) as session, session.begin():
        original = session.get(Posting, posting)
        extra = Posting(
            source_id=original.source_id,
            external_posting_id="outside-batch",
            title="Do not screen this job",
            canonical_job_url="https://example.test/outside",
            apply_url="https://example.test/outside",
            description_text="Not selected.",
            date_provenance="unknown",
            first_seen_at=utc_now(),
            last_seen_at=utc_now(),
            content_hash="outside",
            locations="United States",
            status="active",
        )
        session.add(extra)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        job = json.loads(payload["contents"][0]["parts"][0]["text"])["posting"]
        requests.append(job["id"])
        return httpx.Response(200, json=response(output()))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        first = screen_jobs(
            database[1], profile, api_key="fake", client=client, posting_ids=[posting]
        )
        repeat = screen_jobs(
            database[1], profile, api_key="fake", client=client, posting_ids=[posting]
        )
    assert first["api_calls"] == 2 and repeat["api_calls"] == 0
    assert requests == [posting, posting]
    assert {row.posting_id for row in results(database[1])} == {posting}


def test_empty_selection_never_defaults_to_all_jobs(
    database, posting, profile, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("empty selection must not construct a Gemini client")

    monkeypatch.setattr("jobsfinder_io.screening.genai.Client", forbidden)
    assert (
        screen_jobs(database[1], profile, api_key="fake", posting_ids=[])["api_calls"]
        == 0
    )
    assert results(database[1]) == []


@pytest.mark.parametrize("ids", [[0], [-1], [True], ["1"]])
def test_invalid_selected_ids_are_rejected(database, profile, ids):
    with pytest.raises(ValueError, match="positive integer"):
        screen_jobs(database[1], profile, posting_ids=ids)


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "facts": ["Built a synthetic training application."],
                "skills": ["Python"],
                "available_from": "2027-06-01",
                "us": {"work_authorization": "requires sponsorship"},
                "international": {"priority_countries": ["Germany"]},
                "contact_email": "must-not-send@example.test",
            }
        )
    )
    return path


@pytest.fixture
def posting(database):
    with Session(database[1]) as session, session.begin():
        employer = add_employer(session, "Synthetic")
        source = add_source(
            session, employer.id, "greenhouse", "synthetic", "https://example.test"
        )
        post = Posting(
            source_id=source.id,
            external_posting_id="1",
            title="Integration Engineer",
            canonical_job_url="https://example.test/jobs/1",
            apply_url="https://example.test/jobs/1",
            description_text="Build Python services. 3 years preferred. Sponsorship not specified.",
            date_provenance="unknown",
            first_seen_at=utc_now(),
            last_seen_at=utc_now(),
            content_hash="hash1",
            locations="United States",
            status="active",
        )
        session.add(post)
        session.flush()
        return post.id


def output(**changes):
    result = {
        "disposition": "recommend",
        "score": 82,
        "primary_reason": "Programming-heavy work with preferred experience.",
        "visa_class": "B",
        "start_class": "B",
        "required_experience": None,
        "preferred_experience": "3 years",
        "country": "United States",
        "uncertainty": ["Sponsorship is unconfirmed."],
        "requires_human_review": True,
        "evidence": [
            {
                "quote": "Build Python services.",
                "source_url": "https://example.test/jobs/1",
            }
        ],
    }
    return result | changes


def response(result):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"role": "model", "parts": [{"text": json.dumps(result)}]},
            }
        ],
        "usageMetadata": {"totalTokenCount": 25},
    }


def results(engine):
    with Session(engine) as session:
        return list(
            session.scalars(
                select(ScreeningResult)
                .where(ScreeningResult.stage == "final")
                .order_by(ScreeningResult.id)
            )
        )


def test_profile_excludes_contacts_and_validates_fields(profile):
    assert "contact_email" not in load_profile(profile)
    profile.write_text('{"skills": "invented"}')
    with pytest.raises(ValueError, match="list"):
        load_profile(profile)


def test_two_stages_cache_and_profile_invalidation(database, posting, profile):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert (
            payload["generationConfig"]["responseJsonSchema"]["additionalProperties"]
            is False
        )
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["maxOutputTokens"] == 4096
        assert payload["generationConfig"]["thinkingConfig"]["thinking_level"] == "LOW"
        assert (
            payload["generationConfig"]["responseJsonSchema"]["properties"]["evidence"][
                "minItems"
            ]
            == 1
        )
        assert request.extensions["timeout"]["read"] == 90
        assert "must-not-send" not in payload["contents"][0]["parts"][0]["text"]
        assert "UNTRUSTED DATA" in payload["systemInstruction"]["parts"][0]["text"]
        return httpx.Response(200, json=response(output()))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        counts = screen_jobs(database[1], profile, api_key="fake", client=client)
        assert counts["api_calls"] == 2
        assert (
            screen_jobs(database[1], profile, api_key="fake", client=client)["cached"]
            == 1
        )
        profile.write_text('{"facts": ["Updated synthetic profile"]}')
        assert (
            screen_jobs(database[1], profile, api_key="fake", client=client)[
                "api_calls"
            ]
            == 2
        )
    assert len(requests) == 4
    assert results(database[1])[-1].disposition == "recommend"
    assert results(database[1])[-1].payload["usage"]["total_token_count"] == 25


@pytest.mark.parametrize("status", [500, 503])
def test_retry_requests_are_budgeted_without_hidden_sdk_retries(
    database, posting, profile, monkeypatch, status
):
    requests = []
    monkeypatch.setattr("jobsfinder_io.screening.time.sleep", lambda delay: None)

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                status,
                headers={"Retry-After": "1"},
                json={"error": {"code": status, "message": "temporary"}},
            )
        return httpx.Response(200, json=response(output()))

    with gemini_client(transport=httpx.MockTransport(handler), attempts=5) as client:
        counts = screen_jobs(
            database[1], profile, api_key="fake", max_calls=3, client=client
        )
    assert len(requests) == counts["api_calls"] == 3
    assert results(database[1])[-1].disposition == "recommend"
    with Session(database[1]) as session:
        assert session.scalar(select(TaskRun)).payload["calls"] == 3


def test_retry_cannot_exceed_persistent_request_limit(
    database, posting, profile, monkeypatch
):
    requests = []
    monkeypatch.setattr("jobsfinder_io.screening.time.sleep", lambda delay: None)

    def handler(request):
        requests.append(request)
        return httpx.Response(
            503, json={"error": {"code": 503, "message": "temporary"}}
        )

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        counts = screen_jobs(
            database[1], profile, api_key="fake", max_calls=1, client=client
        )
    assert len(requests) == counts["api_calls"] == 1
    assert (
        results(database[1])[-1].payload["primary_reason"] == "gemini_server_overload"
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_auth_schema_and_unavailable_model_errors_stay_reviewable(
    database, posting, profile, status
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": {"code": status, "message": "private error must not leak"}},
        )

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        counts = screen_jobs(database[1], profile, api_key="fake", client=client)
    assert len(requests) == counts["api_calls"] == 1
    assert results(database[1])[-1].disposition == "needs_review"
    assert "private error" not in json.dumps(results(database[1])[-1].payload)


def test_timeout_is_safe_and_counted(database, posting, profile):
    def handler(request):
        raise httpx.ReadTimeout("secret-key-must-not-leak", request=request)

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        counts = screen_jobs(database[1], profile, api_key="fake", client=client)
    assert counts["api_calls"] == 1
    assert "secret-key" not in json.dumps(results(database[1])[-1].payload)


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "STOP"])
def test_invalid_response_token_usage_is_not_lost(database, posting, profile, finish):
    payload = response(output(evidence=[]))
    payload["candidates"][0]["finishReason"] = finish
    with gemini_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        screen_jobs(database[1], profile, api_key="fake", client=client)
    final = results(database[1])[-1]
    assert final.disposition == "needs_review"
    assert final.payload["usage"]["total_token_count"] == 25


def test_missing_key_never_constructs_sdk_client(
    database, posting, profile, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail(
            "No SDK client should be constructed without an explicit Gemini key"
        )

    monkeypatch.setattr("jobsfinder_io.screening.genai.Client", forbidden)
    assert screen_jobs(database[1], profile)["needs_review"] == 1
    assert (
        screen_jobs(database[1], profile, api_key="fake", max_calls=0)["api_calls"] == 0
    )


def test_model_selection_and_legacy_provider_cache(database, posting, profile):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response(output()))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        screen_jobs(database[1], profile, api_key="fake", client=client)
        with Session(database[1]) as session, session.begin():
            previous = session.scalar(
                select(ScreeningResult).where(ScreeningResult.stage == "final")
            )
            previous.prompt_version = "eligibility-v2"
            previous.model = "gpt-4o-mini|gpt-4o-mini"
        assert (
            screen_jobs(database[1], profile, api_key="fake", client=client)[
                "api_calls"
            ]
            == 2
        )
        assert (
            screen_jobs(
                database[1],
                profile,
                api_key="fake",
                review_model="gemini-configured-review",
                client=client,
            )["api_calls"]
            == 2
        )
    assert DEFAULT_MODEL in requests[0].url.path
    assert "gemini-configured-review" in requests[-1].url.path
    assert results(database[1])[-1].prompt_version == PROMPT_VERSION
    assert len(results(database[1])) == 3


def test_continuation_does_not_issue_unbudgeted_followups(database, posting, profile):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "CONTINUATION",
                        "continuationToken": "not-to-follow",
                        "content": {"parts": [{"text": "{}"}]},
                    }
                ]
            },
        )

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        counts = screen_jobs(
            database[1], profile, api_key="fake", max_calls=1, client=client
        )
    assert len(requests) == counts["api_calls"] == 1
    assert results(database[1])[-1].disposition == "needs_review"


def test_missing_key_and_budget_keep_reviewable_jobs(database, posting, profile):
    assert screen_jobs(database[1], profile)["needs_review"] == 1
    assert results(database[1])[0].payload["primary_reason"] == "gemini_key_missing"
    counts = screen_jobs(database[1], profile, api_key="fake", max_calls=0)
    assert counts["api_calls"] == 0
    assert results(database[1])[-1].payload["primary_reason"] == "api_budget_exhausted"


def test_request_cap_persists_across_invocations(database, posting, profile):
    with gemini_client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=response(output()))
        )
    ) as client:
        first = screen_jobs(
            database[1], profile, api_key="fake", max_calls=1, client=client
        )
        second = screen_jobs(
            database[1], profile, api_key="fake", max_calls=1, client=client
        )
    assert first["api_calls"] == 1
    assert second["api_calls"] == 0
    with Session(database[1]) as session:
        assert session.scalar(select(TaskRun)).payload["calls"] == 1


def test_repeated_exhausted_budget_does_not_create_unattempted_preliminary_rows(
    database, posting, profile
):
    with gemini_client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response(output()))
        )
    ) as client:
        first = screen_jobs(
            database[1], profile, api_key="fake", max_calls=1, client=client
        )
        with Session(database[1]) as session:
            before = len(list(session.scalars(select(ScreeningResult))))
        for _ in range(2):
            assert (
                screen_jobs(
                    database[1], profile, api_key="fake", max_calls=1, client=client
                )["api_calls"]
                == 0
            )
        with Session(database[1]) as session:
            assert len(list(session.scalars(select(ScreeningResult)))) == before
    assert first["api_calls"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {
            "candidates": [
                {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}
            ]
        },
        {"promptFeedback": {"blockReason": "SAFETY"}},
        response(
            output(
                evidence=[
                    {
                        "quote": "Invented quote",
                        "source_url": "https://example.test/jobs/1",
                    }
                ]
            )
        ),
        response(
            output(
                evidence=[
                    {
                        "quote": "Build Python services.",
                        "source_url": "https://attacker.test",
                    }
                ]
            )
        ),
        response(output(score=True)),
    ],
)
def test_malformed_or_ungrounded_output_is_review(database, posting, profile, payload):
    with gemini_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        counts = screen_jobs(database[1], profile, api_key="fake", client=client)
    assert counts["needs_review"] == 1
    assert results(database[1])[-1].disposition == "needs_review"


@pytest.mark.parametrize("pipeline", ["us", "international"])
def test_explicit_exclusion_and_start_are_independent(pipeline):
    text = "Existing work authorization required. Start date flexible."
    value = output(
        preferred_experience=None,
        visa_class="D",
        start_class="B",
        country="Germany" if pipeline == "international" else "US",
        evidence=[
            {
                "quote": "Existing work authorization required.",
                "source_url": "https://example.test/jobs/1",
            }
        ],
    )
    assert (
        validate_result(value, text, "https://example.test/jobs/1")["disposition"]
        == "reject"
    )


def test_unknown_remote_locations_keep_both_policies():
    assert pipelines_for("Worldwide remote") == ("us", "international")
    assert pipelines_for("New York, United States") == ("us",)
    assert pipelines_for("London or New York") == ("us", "international")


def test_unknown_visa_and_unspecified_start_are_not_rejected():
    value = validate_result(
        output(),
        "Build Python services. 3 years preferred.",
        "https://example.test/jobs/1",
    )
    assert value["disposition"] == "recommend"
    assert value["requires_human_review"]


def test_missing_profile_skips_without_network(database):
    assert screen_jobs(database[1], None)["skipped"] == 1


def test_deterministic_filter_preserves_misleading_titles():
    assert (
        deterministic_result(
            {
                "title": "Registered Nurse",
                "text": "Registered Nurse\nTreat patients.",
                "url": "https://example.test",
            }
        )["disposition"]
        == "reject"
    )
    assert (
        deterministic_result(
            {
                "title": "Registered Nurse",
                "text": "Registered Nurse\nBuild software for hospitals.",
                "url": "https://example.test",
            }
        )
        is None
    )
    assert (
        deterministic_result(
            {
                "title": "Analyst",
                "text": "Analyst\nDevelop internal systems.",
                "url": "https://example.test",
            }
        )
        is None
    )


def test_international_remote_evaluates_separate_policies(database, posting, profile):
    with Session(database[1]) as session, session.begin():
        session.get(Posting, posting).locations = "Remote, Germany"
    policies = []

    def handler(request):
        policies.append(
            json.loads(request.content)["systemInstruction"]["parts"][0]["text"]
        )
        return httpx.Response(200, json=response(output(country="Germany")))

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        counts = screen_jobs(database[1], profile, api_key="fake", client=client)
    assert counts["screened"] == 2
    assert counts["api_calls"] == 4
    assert any("Pipeline: international" in prompt for prompt in policies)
    assert {r.pipeline for r in results(database[1])} == {"us", "international"}


def test_unchanged_missing_credentials_do_not_grow_history(database, posting, profile):
    screen_jobs(database[1], profile)
    screen_jobs(database[1], profile)
    assert len(results(database[1])) == 1


def test_changed_content_invalidates_cache(database, posting, profile):
    with gemini_client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=response(output()))
        )
    ) as client:
        screen_jobs(database[1], profile, api_key="fake", client=client)
        with Session(database[1]) as session, session.begin():
            session.get(Posting, posting).content_hash = "material-change"
        assert (
            screen_jobs(database[1], profile, api_key="fake", client=client)[
                "api_calls"
            ]
            == 2
        )


def test_large_descriptions_retain_review_without_billable_calls(
    database, posting, profile
):
    with Session(database[1]) as session, session.begin():
        session.get(Posting, posting).description_text = "x" * 60001
    counts = screen_jobs(database[1], profile, api_key="fake")
    assert counts["api_calls"] == 0
    assert (
        results(database[1])[-1].payload["primary_reason"]
        == "job_text_exceeds_input_limit"
    )


@pytest.mark.parametrize("field", ["visa_class", "start_class"])
def test_unrelated_real_quote_cannot_support_exclusion(field):
    result = validate_result(
        output(**{field: "D", "preferred_experience": None}),
        "Build Python services.",
        "https://example.test/jobs/1",
    )
    assert result["disposition"] == "needs_review"
    assert result[field] == "B"


def test_fixed_start_exclusion_matches_private_availability():
    text = "Must start by 2026-11-01."
    value = output(
        start_class="D",
        preferred_experience=None,
        evidence=[{"quote": text, "source_url": "https://example.test/jobs/1"}],
    )
    assert (
        validate_result(
            value, text, "https://example.test/jobs/1", available_from="2027-06-01"
        )["disposition"]
        == "reject"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Graduate intake May 2027; flexible start dates are available.",
        "Must start by 2027-05-15, but flexible start dates are available to graduates.",
    ],
)
def test_may_graduate_flexible_start_is_not_a_hard_rejection(text):
    value = output(
        start_class="D",
        preferred_experience=None,
        evidence=[{"quote": text, "source_url": "https://example.test/jobs/1"}],
    )
    result = validate_result(
        value, text, "https://example.test/jobs/1", available_from="2027-06-01"
    )
    assert result["disposition"] == "needs_review"
    assert result["start_class"] != "D"


def test_everify_notice_cannot_become_a_sponsorship_exclusion():
    text = "E-Verify Participation Notice. Right to Work Notice."
    value = output(
        visa_class="D",
        preferred_experience=None,
        evidence=[{"quote": text, "source_url": "https://example.test/jobs/1"}],
    )
    result = validate_result(value, text, "https://example.test/jobs/1")
    assert result["disposition"] == "needs_review" and result["visa_class"] == "B"


def test_explicit_no_sponsorship_is_still_an_exclusion():
    text = "We cannot sponsor work visas now or in the future."
    value = output(
        visa_class="D",
        preferred_experience=None,
        evidence=[{"quote": text, "source_url": "https://example.test/jobs/1"}],
    )
    assert (
        validate_result(value, text, "https://example.test/jobs/1")["disposition"]
        == "reject"
    )


def test_supplied_location_quotes_are_valid_evidence(database, posting, profile):
    def handler(request):
        payload = json.loads(request.content)
        assert (
            "United States"
            in json.loads(payload["contents"][0]["parts"][0]["text"])["posting"]["text"]
        )
        return httpx.Response(
            200,
            json=response(
                output(
                    evidence=[
                        {
                            "quote": "United States",
                            "source_url": "https://example.test/jobs/1",
                        }
                    ]
                )
            ),
        )

    with gemini_client(transport=httpx.MockTransport(handler)) as client:
        screen_jobs(database[1], profile, api_key="fake", client=client)
    assert results(database[1])[-1].disposition == "recommend"


@pytest.mark.parametrize(
    "quote",
    [
        "We do not require US citizenship.",
        "No citizenship requirement applies.",
        "No sponsorship restrictions apply.",
        "US citizenship is not required.",
        "No sponsorship is required.",
    ],
)
def test_negated_immigration_restriction_is_never_exclusion(quote):
    value = output(
        visa_class="D",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": "https://example.test/jobs/1"}],
    )
    result = validate_result(value, quote, "https://example.test/jobs/1")
    assert result["disposition"] == "needs_review"
    assert result["visa_class"] == "B"


@pytest.mark.parametrize(
    "quote",
    [
        "We were founded on 2020-01-01. Start date is flexible.",
        "Applications by 2027-01-01; start flexible.",
        "Must apply by 2027-01-01. We welcome flexible start dates.",
    ],
)
def test_non_start_dates_cannot_support_start_exclusion(quote):
    value = output(
        start_class="D",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": "https://example.test/jobs/1"}],
    )
    result = validate_result(
        value, quote, "https://example.test/jobs/1", available_from="2027-06-01"
    )
    assert result["disposition"] == "needs_review"
    assert result["start_class"] == "B"


def test_arbitrary_quote_cannot_claim_visa_support():
    result = validate_result(
        output(visa_class="A", preferred_experience=None),
        "Build Python services.",
        "https://example.test/jobs/1",
    )
    assert result["visa_class"] == "B"
    assert result["disposition"] == "needs_review"


@pytest.mark.parametrize(
    "locations", ["New York; Paris", "United States; Tokyo", "California / France"]
)
def test_other_countries_remain_in_international_pipeline(locations):
    assert pipelines_for(locations) == ("us", "international")
