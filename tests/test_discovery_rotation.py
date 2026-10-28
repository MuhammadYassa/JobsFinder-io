import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io.discovery import discover
from jobsfinder_io.discovery.rotation import (
    COUNTRIES,
    INDUSTRIES,
    US_REGIONS,
    search_plan,
)
from jobsfinder_io.persistence.models import (
    DiscoveryAttempt,
    Employer,
    JobSource,
    TaskRun,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.resolve_public", lambda _: "93.184.216.34"
    )
    monkeypatch.setattr("jobsfinder_io.discovery.network.time.sleep", lambda _: None)


def config_file(tmp_path, config):
    path = tmp_path / "discovery.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def fixture_client(calls):
    def handle(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "directory.example":
            return httpx.Response(
                200,
                text="""
                <a href="https://employer0.example/careers">Confirmed employer</a>
                <a href="https://unknown.example/careers">Unconfirmed employer</a>
                <a href="https://127.0.0.1/private">Unsafe</a>
            """,
                headers={"content-type": "text/html"},
            )
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(200, json={"jobs": [], "meta": {"total": 0}})
        token = request.url.host.split(".")[0]
        return httpx.Response(
            200,
            text=f'<a href="https://boards.greenhouse.io/{token}">Jobs</a>',
            headers={"content-type": "text/html"},
        )

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_daily_batches_persist_and_expand_employer_registry(database, tmp_path):
    engine = database[1]
    path = config_file(
        tmp_path,
        {
            "max_candidates": 3,
            "candidates": [
                {
                    "name": f"Employer {i}",
                    "careers_url": f"https://employer{i}.example/careers",
                }
                for i in range(8)
            ],
        },
    )
    now = datetime(2026, 10, 27, 10, tzinfo=UTC)
    calls = []
    with fixture_client(calls) as client:
        first = discover(engine, path, client=client, now=now)
        second = discover(engine, path, client=client, now=now + timedelta(days=1))
        third = discover(engine, path, client=client, now=now + timedelta(days=2))
    assert first["employers_added"] == second["employers_added"] == 3
    assert third["employers_added"] == 2
    assert first["sources_total"] == 3
    assert second["sources_total"] == 6
    assert third["sources_total"] == 8
    assert third["duplicates"] == 1
    assert sum("boards-api.greenhouse.io" in url for url in calls) == 8
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Employer)) == 8
        assert session.scalar(select(func.count()).select_from(JobSource)) == 8
        cursor = session.scalar(
            select(TaskRun).where(TaskRun.task_key.endswith(":candidates"))
        )
        assert cursor.payload["offset"] == 1


def test_known_board_is_not_revalidated_and_duplicate_check_is_audited(
    database, tmp_path
):
    path = config_file(
        tmp_path,
        [{"name": "Employer", "careers_url": "https://employer0.example/careers"}],
    )
    calls = []
    with fixture_client(calls) as client:
        discover(database[1], path, client=client)
        result = discover(database[1], path, client=client)
    assert result["registered"] == 0
    assert result["duplicates"] == 1
    assert sum("boards-api.greenhouse.io" in url for url in calls) == 1
    with Session(database[1]) as session:
        assert session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.status == "duplicate")
        )


def test_public_directory_requires_confirmed_employer_domains(database, tmp_path):
    path = config_file(
        tmp_path,
        {
            "directories": [
                {
                    "url": "https://directory.example/members",
                    "trusted_domains": ["employer0.example"],
                }
            ]
        },
    )
    calls = []
    with fixture_client(calls) as client:
        result = discover(database[1], path, client=client)
    assert result["registered"] == 1
    assert result["candidates_found"] == 2
    assert result["directories_checked"] == 1
    assert not any("unknown.example" in url for url in calls)
    assert not any("127.0.0.1" in url for url in calls)
    with Session(database[1]) as session:
        candidate = session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.status == "candidate")
        )
        assert candidate.candidate_url == "https://unknown.example/careers"
        assert candidate.payload["directory_url"] == "https://directory.example/members"
        registered = session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.status == "registered")
        )
        assert registered.payload["provenance"]["method"] == "public_directory"


def test_directory_robots_denial_is_persisted_without_registration(database, tmp_path):
    path = config_file(
        tmp_path, {"directories": [{"url": "https://directory.example/members"}]}
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="User-agent: *\nDisallow: /")
        )
    ) as client:
        result = discover(database[1], path, client=client)
    assert result["failed"] == 1
    assert result["registered"] == 0
    with Session(database[1]) as session:
        row = session.scalar(select(DiscoveryAttempt))
        assert row.payload["error"] == "robots_disallowed"


def test_generated_search_plan_covers_all_regions_industries_and_countries():
    plan = search_plan({"rotate_breadth": True})
    assert len(US_REGIONS) == 51
    assert {country for _, country in plan} == {"US", *(code for code, _ in COUNTRIES)}
    text = " ".join(query for query, _ in plan)
    assert all(state in text for state in US_REGIONS)
    assert all(industry in text for industry in INDUSTRIES)
    assert not search_plan({})


def test_search_query_cursor_survives_daily_runs(database, tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "placeholder")
    path = config_file(
        tmp_path,
        {"search": {"provider": "brave", "rotate_breadth": True, "max_queries": 2}},
    )
    queries = []

    def handle(request):
        queries.append(request.url.params["q"])
        return httpx.Response(200, json={"web": {"results": []}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        discover(database[1], path, client=client)
        discover(database[1], path, client=client)
    assert len(queries) == len(set(queries)) == 4


def test_discovery_rejects_naive_time(database, tmp_path):
    path = config_file(tmp_path, [])
    with pytest.raises(ValueError, match="timezone_required"):
        discover(database[1], path, now=datetime(2026, 10, 27))
