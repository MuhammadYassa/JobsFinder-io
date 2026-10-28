import gzip
import json

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io.discovery import discover
from jobsfinder_io.discovery.network import (
    DiscoveryError,
    Fetcher,
    PublicTransport,
    public_host,
    resolve_public,
)
from jobsfinder_io.discovery.service import ats_links
from jobsfinder_io.persistence.models import DiscoveryAttempt, Employer, JobSource


@pytest.fixture(autouse=True)
def offline_discovery(monkeypatch):
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.resolve_public", lambda host: "93.184.216.34"
    )
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.time.sleep", lambda value: None
    )


def candidates_file(tmp_path, contents=None):
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            contents
            if contents is not None
            else [{"name": "Example", "careers_url": "https://example.com/careers"}]
        ),
        encoding="utf-8",
    )
    return path


def mock_client(*, page=None, robots="User-agent: *\nAllow: /", fail_board=False):
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        if request.url.host == "example.com":
            return httpx.Response(
                200,
                text=page or '<a href="https://boards.greenhouse.io/example">Jobs</a>',
                headers={"content-type": "text/html"},
            )
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(
                403 if fail_board else 200, json={"jobs": [], "meta": {"total": 0}}
            )
        raise AssertionError(f"Unexpected request {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_discover_registers_verified_source_and_is_idempotent(database, tmp_path):
    engine = database[1]
    path = candidates_file(tmp_path)
    with mock_client() as client:
        first = discover(engine, path, client=client)
        second = discover(engine, path, client=client)
    assert first["registered"] == 1
    assert second["duplicates"] == 1
    assert first["failed"] == second["failed"] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Employer)) == 1
        sources = list(session.scalars(select(JobSource)))
        assert len(sources) == 1
        assert sources[0].status == "validated"
        assert sources[0].validated_at is not None
        assert sources[0].careers_url == "https://example.com/careers"
        audit = session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.status == "registered")
        )
        assert audit.payload["source_id"] == sources[0].id
        assert audit.payload["official_domain"] == "example.com"


@pytest.mark.parametrize(
    "mode", ["robots", "board", "no_source", "wrong_domain", "unsafe"]
)
def test_failed_checks_never_register_sources(database, tmp_path, mode):
    entry = {"name": "Example", "careers_url": "https://example.com/careers"}
    if mode == "wrong_domain":
        entry["official_domain"] = "different.example"
    if mode == "unsafe":
        entry["careers_url"] = "https://127.0.0.1/careers"
    path = candidates_file(tmp_path, [entry])
    with mock_client(
        robots="User-agent: *\nDisallow: /"
        if mode == "robots"
        else "User-agent: *\nAllow: /",
        page="<p>No jobs</p>" if mode == "no_source" else None,
        fail_board=mode == "board",
    ) as client:
        result = discover(database[1], path, client=client)
    assert result["registered"] == 0
    assert result["failed"] >= 1
    with Session(database[1]) as session:
        assert session.scalar(select(func.count()).select_from(JobSource)) == 0
        assert session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.status == "failed")
        )


def test_ats_link_parser_exact_hosts_and_eu():
    page = """
    <a href="https://jobs.lever.co/acme/a">Job</a>
    <a href="https://jobs.eu.lever.co/acme/b">Job</a>
    <a href="https://jobs.lever.co.evil.example/no">Bad</a>
    <iframe src="https://jobs.ashbyhq.com/other"></iframe>
    <a href="https://job-boards.greenhouse.io/third/jobs/123">Job</a>
    <a href="https://jobs.lever.co/acme/c#section">Duplicate</a>
    """
    links = ats_links(page, "https://example.com/careers")
    assert {(p, token) for p, token, _ in links} == {
        ("lever", "acme"),
        ("lever_eu", "acme"),
        ("ashby", "other"),
        ("greenhouse", "third"),
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://example.com:8443",
        "https://example.com/#part",
        "https://metadata.google.internal/",
    ],
)
def test_public_host_rejects_unsafe_urls(url):
    with pytest.raises(DiscoveryError):
        public_host(url)


def test_dns_rejects_mixed_public_private_answers(monkeypatch):
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.socket.getaddrinfo",
        lambda *a, **k: [
            (None, None, None, None, ("93.184.216.34", 443)),
            (None, None, None, None, ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(DiscoveryError, match="non_public"):
        resolve_public("example.com")


def test_public_transport_pins_address_and_retains_tls_host(monkeypatch):
    transport = PublicTransport()
    captured = []
    monkeypatch.setattr(
        transport.transport,
        "handle_request",
        lambda request: captured.append(request) or httpx.Response(200),
    )
    transport.handle_request(httpx.Request("GET", "https://example.com/careers"))
    request = captured[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"
    transport.close()


def test_cross_host_redirect_refused():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    302, headers={"location": "https://127.0.0.1/secret"}
                )
            )
        ) as client,
        pytest.raises(DiscoveryError),
    ):
        Fetcher(client, spacing=0).get("https://example.com/careers")


def test_transient_retry_is_bounded():
    requests = []
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(503)
            )
        ) as client,
        pytest.raises(DiscoveryError, match="http_503"),
    ):
        Fetcher(client, spacing=0).get("https://example.com/careers")
    assert len(requests) == 3


def test_missing_search_key_keeps_import_fallback(database, tmp_path, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    config = {
        "candidates": [
            {"name": "Example", "careers_url": "https://example.com/careers"}
        ],
        "search": {
            "provider": "brave",
            "queries": ["regional manufacturing employer careers US"],
        },
    }
    with mock_client() as client:
        result = discover(database[1], candidates_file(tmp_path, config), client=client)
    assert result["search_skipped"] == "missing_credentials"
    assert result["registered"] == 1


def test_brave_unknown_domains_are_audited_without_auto_trust(
    database, tmp_path, monkeypatch
):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-placeholder")
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "api.search.brave.com"
        assert request.headers["x-subscription-token"] == "test-placeholder"
        assert request.url.params["country"] == "DE"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Regional Company careers",
                            "url": "https://regional.example/careers",
                        }
                    ]
                }
            },
        )

    config = {
        "search": {
            "provider": "brave",
            "country": "DE",
            "queries": ["regional engineering employers Germany careers"],
            "max_queries": 1,
        }
    }
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = discover(database[1], candidates_file(tmp_path, config), client=client)
    assert result["candidates_found"] == 1
    assert result["registered"] == 0
    assert len(calls) == 1
    with Session(database[1]) as session:
        row = session.scalar(select(DiscoveryAttempt))
        assert row.status == "candidate"
        assert row.method == "brave_search"
        assert "test-placeholder" not in json.dumps(row.payload)


def test_invalid_candidates_file_has_clear_error(database, tmp_path):
    with pytest.raises(DiscoveryError, match="invalid_candidates_file"):
        discover(database[1], tmp_path / "absent.json")


def test_compressed_page_is_decoded_only_once():
    page = '<a href="https://boards.greenhouse.io/example">Jobs</a>'

    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=gzip.compress(page.encode()),
            headers={
                "Content-Encoding": "gzip",
                "Content-Type": "text/html",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            Fetcher(client, spacing=0).career_page("https://example.com/careers")
            == page
        )


def test_long_robots_delay_defers_without_sleeping(monkeypatch):
    sleeps = []
    monkeypatch.setattr("jobsfinder_io.discovery.network.time.sleep", sleeps.append)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, text="User-agent: *\nAllow: /\nCrawl-delay: 9999999\n"
                )
            )
        ) as client,
        pytest.raises(DiscoveryError, match="crawl_delay_exceeds_budget"),
    ):
        Fetcher(client, spacing=0).career_page("https://example.com/careers")
    assert not sleeps
