import json
from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from jobsfinder_io.registry import add_employer, add_source
from jobsfinder_io.sources.adapters import (
    AshbyCollector,
    LeverCollector,
    make_collector,
    source_endpoint,
)
from jobsfinder_io.sources.greenhouse import CollectorError


def lever_job(identity="one"):
    return {
        "id": identity,
        "text": "Software Engineer",
        "descriptionPlain": "Build APIs.",
        "categories": {
            "location": "London",
            "allLocations": ["London", "Berlin", "London"],
        },
        "country": "GB",
        "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
        "additionalPlain": "English team.",
        "hostedUrl": f"https://jobs.lever.co/example/{identity}",
        "applyUrl": f"https://jobs.lever.co/example/{identity}/apply",
    }


def ashby_job(identity="one"):
    return {
        "title": "Backend Engineer",
        "descriptionPlain": "Build Java APIs.",
        "isListed": True,
        "location": "Berlin",
        "secondaryLocations": [{"location": "Berlin"}, {"location": "London"}],
        "publishedAt": "2026-10-01T12:00:00Z",
        "jobUrl": f"https://jobs.ashbyhq.com/example/{identity}",
        "applyUrl": f"https://jobs.ashbyhq.com/example/{identity}/application",
    }


def test_lever_pagination_and_eu():
    requests = []

    def handler(request):
        requests.append(request)
        skip = int(request.url.params["skip"])
        return httpx.Response(200, json=[lever_job(str(skip))] if skip < 2 else [])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = LeverCollector(
            client, region="eu", page_size=1, request_interval=0
        ).fetch_jobs("example")
    assert len(jobs) == 2
    assert all(r.url.host == "api.eu.lever.co" and r.method == "GET" for r in requests)
    assert (
        jobs[0].description_text == "Build APIs.\nRequirements\nPython\nEnglish team."
    )
    assert jobs[0].locations == "Berlin; GB; London"
    assert jobs[0].source_published_at is None
    assert jobs[0].source_updated_at is None


@pytest.mark.parametrize(
    "payload", [None, {}, [None], [dict(lever_job(), applyUrl="javascript:bad")]]
)
def test_lever_partial_payload_rejected(payload):
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=json.dumps(payload))
            )
        ) as client,
        pytest.raises(CollectorError) as exc,
    ):
        LeverCollector(client, request_interval=0).fetch_jobs("example")
    assert exc.value.status == "partial"


@pytest.mark.parametrize("max_pages", [1, 2])
def test_lever_repeated_or_truncated_pagination_is_partial(max_pages):
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=[lever_job()])
            )
        ) as client,
        pytest.raises(CollectorError) as exc,
    ):
        LeverCollector(
            client, page_size=1, max_pages=max_pages, request_interval=0
        ).fetch_jobs("example")
    assert exc.value.status == "partial"


def test_ashby_normalization_dates_and_visibility():
    unlisted = dict(ashby_job("hidden"), isListed=False)
    payload = {"apiVersion": "1", "jobs": [ashby_job(), unlisted]}
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        jobs = AshbyCollector(client).fetch_jobs("example")
    assert len(jobs) == 1
    assert jobs[0].external_posting_id == "one"
    assert jobs[0].locations == "Berlin; London"
    assert jobs[0].source_published_at is None
    assert jobs[0].source_updated_at == datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert "not_original_publication" in jobs[0].date_provenance


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.pop("jobs"),
        lambda p: p.update(apiVersion="2"),
        lambda p: p["jobs"].append(deepcopy(p["jobs"][0])),
        lambda p: p["jobs"][0].update(jobUrl="https://jobs.ashbyhq.com/other/one"),
        lambda p: p["jobs"][0].update(publishedAt="2026-01-01"),
        lambda p: p["jobs"][0].pop("isListed"),
    ],
)
def test_ashby_partial_payload_rejected(change):
    payload = {"apiVersion": "1", "jobs": [ashby_job()]}
    change(payload)
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        ) as client,
        pytest.raises(CollectorError) as exc,
    ):
        AshbyCollector(client).fetch_jobs("example")
    assert exc.value.status == "partial"


@pytest.mark.parametrize("provider", ["lever", "lever_eu", "ashby"])
def test_new_adapter_retry_and_invalid_token(provider):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = make_collector(
            provider, client, request_interval=0, sleep=lambda _: None
        )
        with pytest.raises(CollectorError):
            collector.fetch_jobs("example")
        assert len(calls) == 3
        with pytest.raises(CollectorError, match="invalid_board_token"):
            collector.fetch_jobs("../private")
        assert len(calls) == 3


def test_locations_participate_in_content_hash():
    payloads = [[lever_job()], [lever_job()]]
    payloads[1][0]["categories"]["allLocations"].append("Paris")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payloads.pop(0))
        )
    ) as client:
        collector = LeverCollector(client, request_interval=0)
        assert (
            collector.fetch_jobs("example")[0].content_hash
            != collector.fetch_jobs("example")[0].content_hash
        )


@pytest.mark.parametrize("provider", ["lever", "lever_eu", "ashby"])
def test_registry_new_providers(database, provider):
    with Session(database[1]) as session, session.begin():
        employer = add_employer(session, "Example")
        source = add_source(
            session, employer.id, provider, "example", "https://example.com/careers"
        )
        assert source.api_endpoint == source_endpoint(provider, "example")
        assert source.status == "candidate"
