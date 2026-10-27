import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from jobsfinder_io.cli import main
from jobsfinder_io.ingestion import polling
from jobsfinder_io.ingestion.polling import poll_source
from jobsfinder_io.persistence.models import JobSource, PollRun, Posting
from jobsfinder_io.registry import add_employer, add_source, validate_source
from jobsfinder_io.sources.greenhouse import GreenhouseCollector


@pytest.fixture
def registered(database):
    _, engine = database
    with Session(engine) as session, session.begin():
        employer = add_employer(session, "Synthetic employer")
        source = add_source(
            session, employer.id, "greenhouse", "example", "https://example.com/careers"
        )
        validate_source(
            session,
            source.id,
            official_association_confirmed=True,
            public_access_confirmed=True,
        )
        source_id = source.id
    return source_id


@pytest.fixture
def board():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "greenhouse_jobs.json").read_text()
    )
    state = SimpleNamespace(
        payload=payload,
        error=None,
        detail_error=None,
        details={},
        requests=[],
        status=200,
    )

    def handler(request):
        state.requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "boards-api.greenhouse.io"
        if request.url.path.endswith("/jobs"):
            if state.error:
                raise state.error
            return httpx.Response(state.status, json=state.payload)
        if state.detail_error:
            return httpx.Response(state.detail_error)
        identity = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json=state.details.get(identity, {"id": identity}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        state.collector = GreenhouseCollector(
            client, request_interval=0, sleep=lambda delay: None
        )
        yield state


def rows(engine, model):
    with Session(engine) as session:
        return list(session.scalars(select(model).order_by(model.id)))


def poll(database, registered, board):
    return poll_source(database[1], registered, collector=board.collector)


def empty(board):
    board.payload = {"jobs": [], "meta": {"total": 0}}


def test_baseline_repeat_new_and_update(database, registered, board):
    first = poll(database, registered, board)
    assert (first.status, first.observed, first.baseline, first.new) == (
        "complete_success",
        2,
        2,
        0,
    )
    original = rows(database[1], Posting)
    assert [job.external_posting_id for job in original] == ["101", "102"]
    assert all(job.status == "active" for job in original)
    assert original[0].external_requisition_id == "REQ-7"
    assert original[0].source_published_at is None
    assert original[0].source_updated_at is not None
    assert "absent" in original[0].date_provenance
    second = poll(database, registered, board)
    assert (second.baseline, second.new, second.updated, second.unchanged) == (
        0,
        0,
        0,
        2,
    )
    assert len(board.requests) == 4  # two list requests, two initial details
    added = deepcopy(board.payload["jobs"][0])
    added.update(id=103, absolute_url="https://example.com/103")
    board.payload["jobs"].append(added)
    board.payload["meta"]["total"] = 3
    third = poll(database, registered, board)
    assert (third.new, third.unchanged) == (1, 2)
    assert poll(database, registered, board).new == 0
    board.payload["jobs"][0]["content"] = "<p>Updated responsibilities</p>"
    changed = poll(database, registered, board)
    assert (changed.updated, changed.new) == (1, 0)
    final = rows(database[1], Posting)
    assert len(final) == 3
    assert final[0].id == original[0].id
    assert final[0].first_seen_at == original[0].first_seen_at
    assert final[0].last_seen_at > original[0].last_seen_at
    assert final[0].description_text == "Updated responsibilities"
    runs = rows(database[1], PollRun)
    assert len(runs) == 5
    assert all(
        run.status == "complete_success" and run.completed_at is not None
        for run in runs
    )
    source = rows(database[1], JobSource)[0]
    assert source.last_success_at == runs[-1].completed_at
    assert source.last_attempt_at == runs[-1].started_at
    assert source.consecutive_failures == 0


def test_missing_failed_partial_closed_and_reappeared(database, registered, board):
    poll(database, registered, board)
    original = rows(database[1], Posting)[0]
    payload = deepcopy(board.payload)
    empty(board)
    missing = poll(database, registered, board)
    assert missing.missing == 2 and missing.closed == 0
    assert all(job.status == "missing_pending" for job in rows(database[1], Posting))
    last_success = rows(database[1], JobSource)[0].last_success_at
    board.error = httpx.ReadTimeout("Synthetic timeout")
    failed = poll(database, registered, board)
    assert failed.status == "failed" and failed.error_code == "timeout"
    board.error = None
    board.payload = {"jobs": [], "meta": {"total": 2}}
    partial = poll(database, registered, board)
    assert partial.status == "partial"
    assert all(job.status == "missing_pending" for job in rows(database[1], Posting))
    source = rows(database[1], JobSource)[0]
    assert source.last_success_at == last_success
    assert source.consecutive_failures == 2
    empty(board)
    assert poll(database, registered, board).closed == 2
    assert all(job.status == "closed" for job in rows(database[1], Posting))
    assert poll(database, registered, board).closed == 0
    board.payload = payload
    back = poll(database, registered, board)
    assert (back.reappeared, back.new) == (2, 0)
    restored = rows(database[1], Posting)[0]
    assert restored.status == "active"
    assert restored.id == original.id
    assert restored.first_seen_at == original.first_seen_at
    assert rows(database[1], JobSource)[0].consecutive_failures == 0


def test_reappearance_after_one_miss_resets_closure_state(database, registered, board):
    payload = deepcopy(board.payload)
    poll(database, registered, board)
    empty(board)
    poll(database, registered, board)
    board.payload = payload
    assert poll(database, registered, board).reappeared == 2
    empty(board)
    assert poll(database, registered, board).closed == 0
    assert all(job.status == "missing_pending" for job in rows(database[1], Posting))


def test_empty_baseline_and_first_success_after_failure(database, registered, board):
    board.status = 404
    assert poll(database, registered, board).status == "failed"
    assert rows(database[1], Posting) == []
    board.status = 200
    baseline = poll(database, registered, board)
    assert baseline.baseline == 2 and baseline.new == 0
    empty(board)
    assert poll(database, registered, board).status == "complete_success"


def test_empty_board_baseline_then_new_jobs(database, registered, board):
    payload = board.payload
    empty(board)
    first = poll(database, registered, board)
    assert first.status == "complete_success" and first.observed == 0
    board.payload = payload
    assert poll(database, registered, board).new == 2


def test_malformed_listing_does_not_partially_write_or_establish_baseline(
    database, registered, board
):
    original = deepcopy(board.payload)
    board.payload["jobs"][1].pop("content")
    assert poll(database, registered, board).status == "partial"
    assert rows(database[1], Posting) == []
    board.payload = original
    assert poll(database, registered, board).baseline == 2


def test_publication_enrichment_failure_is_visible_and_can_recover(
    database, registered, board
):
    board.detail_error = 503
    summary = poll(database, registered, board)
    assert summary.status == "complete_success"  # list coverage is still complete
    assert summary.enrichment_failed == 2
    assert summary.error_code == "publication_enrichment_failed:2"
    assert rows(database[1], PollRun)[0].error_code == summary.error_code
    entry = rows(database[1], Posting)[0]
    assert entry.source_published_at is None
    assert "http_503" in entry.date_provenance
    board.detail_error = None
    board.details[101] = {"id": 101, "first_published": "2026-09-01T10:00:00-04:00"}
    recovered = poll(database, registered, board)
    assert recovered.new == 0 and recovered.updated == 0
    entry = rows(database[1], Posting)[0]
    assert entry.source_published_at.isoformat() == "2026-09-01T14:00:00+00:00"
    assert entry.date_provenance == "greenhouse.detail.first_published"
    assert rows(database[1], PollRun)[-1].http_status == 200


def test_detail_budget_is_bounded_and_remaining_jobs_enriched_later(
    database, registered, board
):
    first = poll_source(
        database[1], registered, collector=board.collector, detail_budget=1
    )
    assert first.enrichment_failed == 1
    assert len(board.requests) == 2
    assert "budget" in rows(database[1], Posting)[1].date_provenance
    second = poll_source(
        database[1], registered, collector=board.collector, detail_budget=1
    )
    assert second.enrichment_failed == 0
    assert len(board.requests) == 4


@pytest.mark.parametrize("status", ["candidate", "paused"])
def test_unvalidated_or_paused_source_is_recorded_without_http(
    database, registered, board, status
):
    with Session(database[1]) as session, session.begin():
        session.get(JobSource, registered).status = status
    result = poll(database, registered, board)
    assert result.status == "failed"
    assert board.requests == []
    assert rows(database[1], PollRun)[0].error_code == "source_not_pollable"
    assert rows(database[1], JobSource)[0].status == status


def test_stored_endpoint_is_never_fetched(database, registered, board):
    with Session(database[1]) as session, session.begin():
        session.get(JobSource, registered).api_endpoint = "http://localhost/private"
    assert poll(database, registered, board).status == "complete_success"
    assert all(
        request.url.host == "boards-api.greenhouse.io" for request in board.requests
    )


def test_overlapping_poll_is_rejected_and_recorded(database, registered, board):
    with Session(database[1]) as session, session.begin():
        session.add(PollRun(source_id=registered))
    result = poll(database, registered, board)
    assert result.error_code == "poll_in_progress"
    assert len(rows(database[1], PollRun)) == 2
    assert board.requests == []


def test_publication_evidence_survives_repeats_and_update_timestamp_changes(
    database, registered, board
):
    board.details[101] = {"id": 101, "first_published": "2026-09-01T12:00:00Z"}
    poll(database, registered, board)
    before = rows(database[1], Posting)[0]
    board.payload["jobs"][0]["updated_at"] = "2026-10-02T12:00:00Z"
    result = poll(database, registered, board)
    after = rows(database[1], Posting)[0]
    assert result.updated == 0 and result.new == 0
    assert after.source_updated_at != before.source_updated_at
    assert after.source_published_at == before.source_published_at
    assert after.date_provenance == "greenhouse.detail.first_published"


def test_rate_limit_stops_remaining_optional_detail_requests(
    database, registered, board
):
    board.detail_error = 429
    result = poll(database, registered, board)
    assert result.status == "complete_success" and result.enrichment_failed == 2
    assert len(board.requests) == 4  # list, three bounded tries for first detail
    assert "detail_rate_limited" in rows(database[1], Posting)[1].date_provenance


def test_snapshot_database_failure_rolls_back_jobs_and_marks_poll_failed(
    database, registered, board, monkeypatch
):
    actual_apply = polling.apply_snapshot

    def fail_after_flush(*args):
        actual_apply(*args)
        raise SQLAlchemyError("Synthetic database failure after posting flush")

    monkeypatch.setattr(polling, "apply_snapshot", fail_after_flush)
    result = poll(database, registered, board)
    assert result.status == "failed" and result.error_code == "persistence_error"
    assert result.baseline == result.new == 0
    assert rows(database[1], Posting) == []
    assert rows(database[1], PollRun)[0].status == "failed"
    assert rows(database[1], JobSource)[0].last_success_at is None
    monkeypatch.setattr(polling, "apply_snapshot", actual_apply)
    assert poll(database, registered, board).baseline == 2


def test_unexpected_interruption_is_recorded_then_reraised(
    database, registered, board, monkeypatch
):
    def interrupted(_token):
        raise RuntimeError("Synthetic unexpected failure")

    monkeypatch.setattr(board.collector, "fetch_jobs", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic"):
        poll(database, registered, board)
    assert rows(database[1], PollRun)[0].error_code == "interrupted"
    assert rows(database[1], Posting) == []


def test_boards_have_independent_baselines_and_job_states(database, registered, board):
    engine = database[1]
    with Session(engine) as session, session.begin():
        employer_id = session.get(JobSource, registered).employer_id
        other = add_source(
            session, employer_id, "greenhouse", "another", "https://example.com"
        )
        validate_source(
            session,
            other.id,
            official_association_confirmed=True,
            public_access_confirmed=True,
        )
        other_id = other.id
    assert poll(database, registered, board).baseline == 2
    assert poll_source(engine, other_id, collector=board.collector).baseline == 2
    empty(board)
    poll(database, registered, board)
    posts = rows(engine, Posting)
    assert len(posts) == 4
    assert all(post.status == "active" for post in posts if post.source_id == other_id)
    assert all(
        post.status == "missing_pending"
        for post in posts
        if post.source_id == registered
    )


def test_cli_http_to_sqlite(database, registered, monkeypatch, capsys):
    calls = []
    job = json.loads(
        (Path(__file__).parent / "fixtures" / "greenhouse_jobs.json").read_text()
    )["jobs"][0]

    def handle(_transport, request):
        calls.append(request)
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": [job], "meta": {"total": 1}})
        return httpx.Response(
            200, json={"id": 101, "first_published": "2026-09-01T12:00:00Z"}
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    args = ["--db", str(database[0]), "poll-source", "--source-id", str(registered)]
    assert main(args) == 0
    assert "baseline=1" in capsys.readouterr().out
    assert len(calls) == 2
    assert len(rows(database[1], Posting)) == 1
    assert main(args) == 0
    assert "unchanged=1" in capsys.readouterr().out
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, r: httpx.Response(404)
    )
    assert main(args) == 1
    assert "failed" in capsys.readouterr().out
    assert rows(database[1], PollRun)[-1].status == "failed"
