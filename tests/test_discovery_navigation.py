"""Trusted directory/homepage navigation stays bounded and fail-closed."""

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsfinder_io.discovery import discover
from jobsfinder_io.persistence.models import DiscoveryAttempt, JobSource


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.resolve_public", lambda _: "93.184.216.34"
    )
    monkeypatch.setattr("jobsfinder_io.discovery.network.time.sleep", lambda _: None)


def config_path(tmp_path, *, directory=False):
    value = (
        {
            "directories": [
                {
                    "url": "https://directory.example/members",
                    "trusted_domains": ["employer.example"],
                }
            ]
        }
        if directory
        else [
            {
                "name": "Employer",
                "careers_url": "https://employer.example/",
                "official_domain": "employer.example",
            }
        ]
    )
    path = tmp_path / "navigation.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def client_for(pages, calls, *, robots=None):
    def handle(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            rules = (robots or {}).get(request.url.host)
            return httpx.Response(200, text=rules) if rules else httpx.Response(404)
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(200, json={"jobs": [], "meta": {"total": 0}})
        return httpx.Response(
            200, text=pages[url], headers={"content-type": "text/html"}
        )

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_directory_homepage_reaches_actual_careers_page_and_registers(
    database, tmp_path
):
    pages = {
        "https://directory.example/members": '<a href="https://employer.example/">Employer</a>',
        "https://employer.example/": '<a href="/company/careers">Join us</a>',
        "https://employer.example/company/careers": '<a href="https://boards.greenhouse.io/employer">Open roles</a>',
    }
    calls = []
    with client_for(pages, calls) as client:
        first = discover(
            database[1], config_path(tmp_path, directory=True), client=client
        )
        repeat = discover(
            database[1], config_path(tmp_path, directory=True), client=client
        )
    assert first["registered"] == 1 and repeat["duplicates"] == 1
    with Session(database[1]) as session:
        source = session.scalar(select(JobSource))
        assert source.careers_url == "https://employer.example/company/careers"
        assert source.status == "validated"
        audit = session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.status == "registered")
        )
        provenance = audit.payload["provenance"]
        assert provenance["method"] == "official_careers_navigation"
        assert provenance["seed_url"] == "https://employer.example/"
        assert provenance["source"]["method"] == "public_directory"


def test_only_trusted_domain_explicit_career_links_are_followed(database, tmp_path):
    pages = {
        "https://employer.example/": """
        <a href="https://evil.example/careers">Unknown</a>
        <a href="https://employer.example.evil.example/jobs">Lookalike</a>
        <a href="https://127.0.0.1/careers">Private</a>
        <a href="http://employer.example/jobs">Insecure</a>
        <a href="https://user:pass@employer.example/jobs">Credentials</a>
        <a href="/pricing">Not careers</a>
        <a href="/careers#roles">Careers</a>
        """,
        "https://employer.example/careers": '<a href="https://boards.greenhouse.io/employer">Open roles</a>',
    }
    calls = []
    with client_for(pages, calls) as client:
        result = discover(database[1], config_path(tmp_path), client=client)
    assert result["registered"] == 1
    assert not any(
        "evil.example" in url or "127.0.0.1" in url or "pricing" in url for url in calls
    )
    assert "https://employer.example/careers" in calls


def test_navigation_is_limited_to_three_pages_and_one_level(database, tmp_path):
    pages = {
        "https://employer.example/": "".join(
            f'<a href="/careers/{i}">Jobs</a>' for i in range(5)
        )
    }
    for i in range(3):
        pages[f"https://employer.example/careers/{i}"] = (
            '<a href="/jobs/deeper">More jobs</a>'
        )
    calls = []
    with client_for(pages, calls) as client:
        result = discover(database[1], config_path(tmp_path), client=client)
    assert result["registered"] == 0 and result["failed"] == 1
    assert len([url for url in calls if "/careers/" in url]) == 3
    assert not any("deeper" in url for url in calls)


def test_subdomain_robots_denial_is_audited_without_unsafe_following(
    database, tmp_path
):
    pages = {
        "https://employer.example/": '<a href="https://careers.employer.example/">Jobs</a>',
    }
    calls = []
    with client_for(
        pages, calls, robots={"careers.employer.example": "User-agent: *\nDisallow: /"}
    ) as client:
        result = discover(database[1], config_path(tmp_path), client=client)
    assert result["registered"] == 0
    assert "https://careers.employer.example/" not in calls
    with Session(database[1]) as session:
        failure = session.scalar(
            select(DiscoveryAttempt).where(
                DiscoveryAttempt.method == "official_careers_navigation"
            )
        )
        assert failure.payload["error"] == "robots_disallowed"


def test_unconfirmed_directory_employer_is_not_followed(database, tmp_path):
    pages = {
        "https://directory.example/members": '<a href="https://unknown.example/">New employer</a>'
    }
    path = tmp_path / "unknown.json"
    path.write_text(
        json.dumps({"directories": [{"url": "https://directory.example/members"}]})
    )
    calls = []
    with client_for(pages, calls) as client:
        result = discover(database[1], path, client=client)
    assert result["candidates_found"] == 1 and result["registered"] == 0
    assert not any("unknown.example" in url for url in calls)
