import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from jobsfinder_io.sources.greenhouse import (
    CollectorError,
    GreenhouseCollector,
    normalize_description,
)


@pytest.fixture
def payload():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "greenhouse_jobs.json").read_text()
    )


def test_list_normalization_and_distinct_ids(payload):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GreenhouseCollector(client, request_interval=0).fetch_jobs("example")
    assert [job.external_posting_id for job in result] == ["101", "102"]
    assert result[0].external_requisition_id == "REQ-7"
    assert result[0].description_text == "Build software & learn."
    assert result[0].source_updated_at == datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert result[0].source_published_at is None
    assert result[0].content_hash != ""
    assert requests[0].url.params["content"] == "true"
    assert requests[0].url.host == "boards-api.greenhouse.io"
    assert requests[0].method == "GET"


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.pop("jobs"),
        lambda p: p.pop("meta"),
        lambda p: p["meta"].update(total=3),
        lambda p: p["meta"].update(total=True),
        lambda p: p["jobs"].append(deepcopy(p["jobs"][0])),
        lambda p: p["jobs"][0].pop("content"),
        lambda p: p["jobs"][0].update(id=None),
        lambda p: p["jobs"][0].update(id=True),
        lambda p: p["jobs"][0].update(title=""),
        lambda p: p["jobs"][0].update(updated_at="not-a-date"),
        lambda p: p["jobs"][0].update(updated_at="2026-01-01T12:00:00"),
        lambda p: p["jobs"][0].update(absolute_url="javascript:alert(1)"),
    ],
)
def test_incomplete_payload_never_becomes_empty_list(payload, change):
    change(payload)
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        ) as client,
        pytest.raises(CollectorError) as exc,
    ):
        GreenhouseCollector(client, request_interval=0).fetch_jobs("example")
    assert exc.value.status == "partial"


@pytest.mark.parametrize(
    "status,attempts", [(404, 1), (403, 1), (302, 1), (429, 3), (500, 3), (503, 3)]
)
def test_http_errors_and_bounded_retries(status, attempts):
    requests = []
    sleeps = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "http://localhost/private"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(CollectorError) as exc,
    ):
        GreenhouseCollector(client, request_interval=0, sleep=sleeps.append).fetch_jobs(
            "example"
        )
    assert exc.value.http_status == status
    assert len(requests) == attempts
    assert all(r.url.host == "boards-api.greenhouse.io" for r in requests)
    assert len(sleeps) == attempts - 1


def test_timeout_recovery_and_retry_after():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("Synthetic timeout", request=request)
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"jobs": [], "meta": {"total": 0}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert (
            GreenhouseCollector(
                client, request_interval=0, sleep=sleeps.append
            ).fetch_jobs("example")
            == []
        )
    assert len(calls) == 3
    assert sleeps[-1] >= 3


def test_long_retry_after_stops_without_retrying_early():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(CollectorError),
    ):
        GreenhouseCollector(client, request_interval=0).fetch_jobs("example")
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"not json", b"null", b"[]"])
def test_malformed_json(body):
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
        ) as client,
        pytest.raises(CollectorError),
    ):
        GreenhouseCollector(client, request_interval=0).fetch_jobs("example")


def test_response_size_bound():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"x" * 100)
            )
        ) as client,
        pytest.raises(CollectorError, match="response_too_large"),
    ):
        GreenhouseCollector(
            client, request_interval=0, max_response_bytes=50
        ).fetch_jobs("example")


@pytest.mark.parametrize(
    "token", ["../other", "https://localhost", "x?redirect=evil", "", "x/y"]
)
def test_invalid_board_token_never_requests(token):
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: pytest.fail("unexpected request"))
        ) as client,
        pytest.raises(CollectorError, match="invalid_board_token"),
    ):
        GreenhouseCollector(client).fetch_jobs(token)


def test_hash_ignores_formatting_and_update_date(payload):
    responses = [deepcopy(payload), deepcopy(payload)]
    responses[1]["jobs"][0]["content"] = "<div> Build   software &amp; learn. </div>"
    responses[1]["jobs"][0]["updated_at"] = "2026-10-02T12:00:00Z"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=responses.pop(0))
        )
    ) as client:
        collector = GreenhouseCollector(client, request_interval=0)
        first = collector.fetch_jobs("example")[0]
        second = collector.fetch_jobs("example")[0]
    assert first.content_hash == second.content_hash
    assert first.source_updated_at != second.source_updated_at


def test_description_keeps_paragraphs_and_omits_scripts():
    assert (
        normalize_description(
            "<p>Build <b>tools</b>.</p><p>Learn.</p><script>bad()</script>"
        )
        == "Build tools.\nLearn."
    )


@pytest.mark.parametrize(
    "detail",
    [
        {"id": 999, "first_published": "2026-01-01T12:00:00Z"},
        {"id": 101, "first_published": "not-a-date"},
        {"id": 101, "first_published": "2026-01-01T12:00:00"},
        None,
    ],
)
def test_bad_publication_evidence_is_rejected(payload, detail):
    responses = [payload, detail]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=json.dumps(responses.pop(0)).encode())
        )
    ) as client:
        collector = GreenhouseCollector(client, request_interval=0)
        job = collector.fetch_jobs("example")[0]
        with pytest.raises(CollectorError, match="invalid_job_detail"):
            collector.enrich_publication("example", job)


def test_request_spacing_uses_a_clock_without_real_sleep(monkeypatch):
    from jobsfinder_io.sources import greenhouse

    clock = [0.0]
    requests = []
    monkeypatch.setattr(greenhouse.time, "monotonic", lambda: clock[0])

    def handler(request):
        requests.append(clock[0])
        return httpx.Response(200, json={"jobs": [], "meta": {"total": 0}})

    def sleep(delay):
        clock[0] += delay

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = GreenhouseCollector(client, sleep=sleep)
        collector.fetch_jobs("example")
        collector.fetch_jobs("example")
    assert requests == [0.0, 1.0]
