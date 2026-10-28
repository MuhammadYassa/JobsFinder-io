"""Discover ATS links on official pages, verify feeds, then register atomically."""

import json
import os
import re
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from jobsfinder_io.discovery.network import (
    DiscoveryError,
    Fetcher,
    PublicTransport,
    public_host,
)
from jobsfinder_io.discovery.providers import BraveSearchProvider
from jobsfinder_io.discovery.rotation import reserve_batch, search_plan
from jobsfinder_io.persistence.models import DiscoveryAttempt, Employer, JobSource
from jobsfinder_io.registry import (
    add_employer,
    add_source,
    normalize_domain,
    validate_source,
)
from jobsfinder_io.sources.adapters import make_collector
from jobsfinder_io.sources.greenhouse import CollectorError

ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.eu.lever.co": "lever_eu",
    "jobs.ashbyhq.com": "ashby",
}
CAREER_PATH = re.compile(
    r"(?:^|/)(?:careers?|jobs?|join-us|work-with-us)(?:[/_-]|$)", re.I
)
MAX_CAREER_PAGES = 3


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"a", "iframe"}:
            for key, value in attrs:
                if key == ("href" if tag == "a" else "src") and value:
                    self.links.append(value)


def ats_links(page: str, base_url: str) -> list[tuple[str, str, str]]:
    parser = Links()
    parser.feed(page)
    found: dict[tuple[str, str], str] = {}
    for href in parser.links:
        url = urljoin(base_url, href)
        try:
            host = public_host(url.split("#", 1)[0])
        except DiscoveryError:
            continue
        provider = ATS_HOSTS.get(host)
        if provider is None:
            continue
        parts = urlsplit(url).path.strip("/").split("/")
        token = parts[0]
        if re.fullmatch(r"[A-Za-z0-9_-]+", token):
            found[provider, token] = f"https://{host}/{token}"
    return [(provider, token, url) for (provider, token), url in sorted(found.items())]


def _find_careers_source(
    engine: Engine, fetcher: Fetcher, url: str, domain: str
) -> tuple[str, list[tuple[str, str, str]]]:
    """Follow only explicit, bounded careers links on a confirmed employer site.

    Directory members commonly link homepages rather than career pages. This
    one-level navigation fills that gap without guessing URLs, trusting new
    domains or changing the transport's robots/redirect/public-address rules.
    """
    page = fetcher.career_page(url)
    links = ats_links(page, url)
    if links:
        return url, links
    parser = Links()
    parser.feed(page)
    candidates = []
    for href in parser.links:
        candidate_url = urljoin(url, href).split("#", 1)[0]
        if candidate_url == url or candidate_url in candidates:
            continue
        try:
            host = public_host(candidate_url)
        except DiscoveryError:
            continue
        if not (host == domain or host.endswith("." + domain)):
            continue
        path = urlsplit(candidate_url).path
        if not CAREER_PATH.search(path) and not host.startswith(("careers.", "jobs.")):
            continue
        candidates.append(candidate_url)
        if len(candidates) == MAX_CAREER_PAGES:
            break
    for candidate_url in candidates:
        evidence = {"seed_url": url, "official_domain": domain}
        try:
            links = ats_links(fetcher.career_page(candidate_url), candidate_url)
        except DiscoveryError as exc:
            _audit(
                engine,
                candidate_url,
                "official_careers_navigation",
                "failed",
                {**evidence, "error": str(exc)},
            )
            continue
        _audit(
            engine,
            candidate_url,
            "official_careers_navigation",
            "source_link_found" if links else "no_supported_source",
            evidence,
        )
        if links:
            return candidate_url, links
    return url, []


def _audit(engine: Engine, url: str, method: str, status: str, payload: dict) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            DiscoveryAttempt(
                candidate_url=url, method=method, status=status, payload=payload
            )
        )


def _register(
    engine: Engine, candidate: dict, domain: str, links: list
) -> tuple[int, int, int]:
    added, duplicates, employers_added = 0, 0, 0
    with Session(engine) as session, session.begin():
        # Obtain SQLite's writer lock before checking identities to serialize
        # concurrent discovery passes without holding locks over network calls.
        session.execute(update(Employer).where(Employer.id == -1).values(name=""))
        employer = session.scalar(
            select(Employer).where(Employer.official_domain == domain)
        )
        for provider, token, board_url in links:
            existing = session.scalar(
                select(JobSource).where(
                    JobSource.provider == provider, JobSource.board_identifier == token
                )
            )
            if existing is not None:
                duplicates += 1
                continue
            if employer is None:
                employer = add_employer(session, candidate["name"], domain)
                employers_added += 1
            source = add_source(
                session, employer.id, provider, token, candidate["careers_url"]
            )
            validate_source(
                session,
                source.id,
                official_association_confirmed=True,
                public_access_confirmed=True,
            )
            session.add(
                DiscoveryAttempt(
                    candidate_url=candidate["careers_url"],
                    method="official_careers_link",
                    status="registered",
                    payload={
                        "source_id": source.id,
                        "provider": provider,
                        "board_identifier": token,
                        "board_url": board_url,
                        "official_domain": domain,
                        "provenance": candidate.get("provenance", "confirmed_import"),
                    },
                )
            )
            added += 1
    return added, duplicates, employers_added


def _search_candidates(
    engine: Engine, config: dict, fetcher: Fetcher, stats: dict, key: str, now: datetime
):
    search = config.get("search", {})
    if not search:
        return []
    if not isinstance(search, dict):
        raise DiscoveryError("invalid_search_config")
    if search.get("provider") != "brave":
        raise DiscoveryError("unsupported_search_provider")
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        stats["search_skipped"] = "missing_credentials"
        return []
    queries = search_plan(search)
    limit = search.get("max_queries", 2)
    if not isinstance(limit, int) or not 0 <= limit <= 20:
        raise DiscoveryError("invalid_search_budget")
    indices = reserve_batch(engine, key + ":search", len(queries), limit, now)
    queries = [queries[index] for index in indices]
    domains = search.get("trusted_domains", [])
    if not isinstance(domains, list) or not all(isinstance(d, str) for d in domains):
        raise DiscoveryError("invalid_trusted_domains")
    trusted = {normalize_domain(d) for d in domains}
    provider = BraveSearchProvider(fetcher, api_key)
    candidates = []
    for query, country in queries:
        try:
            # Brave's country filter is a supported-market enum, not every
            # ISO country. Keep the named target in the query and use a known
            # supported fallback for IE/AE/SG rather than send invalid values.
            filter_country = (
                search.get("fallback_country", "US")
                if country in {"IE", "AE", "SG"}
                else country
            )
            results = provider.search(query, country=filter_country)
        except DiscoveryError as exc:
            _audit(
                engine,
                "https://api.search.brave.com",
                "brave_search",
                "failed",
                {"error": str(exc), "query": query, "country": country},
            )
            stats["failed"] += 1
            continue
        stats["search_queries"] += 1
        for row in results:
            try:
                domain = public_host(row["careers_url"])
            except DiscoveryError:
                continue
            # Search results prove discovery, not employer ownership. Never
            # auto-activate sources from arbitrary aggregators or snippets.
            status = "candidate" if domain not in trusted else "trusted_candidate"
            _audit(
                engine,
                row["careers_url"],
                "brave_search",
                status,
                {
                    "name": row["name"],
                    "official_domain": domain,
                    "query": query,
                    "country": country,
                },
            )
            stats["candidates_found"] += 1
            if domain in trusted and domain not in ATS_HOSTS:
                candidates.append(
                    {**row, "official_domain": domain, "provenance": "brave_search"}
                )
    return candidates


def _directory_candidates(
    engine: Engine, config: dict, fetcher: Fetcher, stats: dict, key: str, now: datetime
) -> list[dict]:
    """Read configured public directories without treating links as ownership.

    A directory is only candidate evidence. Explicit per-directory trusted
    domains are required before following employer links or activating sources.
    """
    directories = config.get("directories", [])
    if not isinstance(directories, list):
        raise DiscoveryError("invalid_directories")
    limit = config.get("max_directories", 2)
    if not isinstance(limit, int) or not 0 <= limit <= 20:
        raise DiscoveryError("invalid_directory_budget")
    candidates = []
    indices = reserve_batch(engine, key + ":directories", len(directories), limit, now)
    stats["directories_checked"] = 0
    for index in indices:
        directory = directories[index]
        url = directory.get("url", "") if isinstance(directory, dict) else ""
        try:
            if not isinstance(url, str):
                raise DiscoveryError("invalid_directory")
            public_host(url)
            domains = directory.get("trusted_domains", [])
            if not isinstance(domains, list) or not all(
                isinstance(d, str) for d in domains
            ):
                raise DiscoveryError("invalid_trusted_domains")
            trusted = {normalize_domain(domain) for domain in domains}
            max_links = directory.get("max_links", 100)
            if not isinstance(max_links, int) or not 1 <= max_links <= 1000:
                raise DiscoveryError("invalid_directory_link_budget")
            parser = Links()
            parser.feed(fetcher.career_page(url))
            stats["directories_checked"] += 1
            links = list(dict.fromkeys(urljoin(url, href) for href in parser.links))
            link_indices = reserve_batch(
                engine,
                key + ":links:" + sha256(url.encode()).hexdigest()[:16],
                len(links),
                max_links,
                now,
            )
            for link_index in link_indices:
                candidate_url = links[link_index].split("#", 1)[0]
                try:
                    host = public_host(candidate_url)
                except DiscoveryError:
                    continue
                if host in ATS_HOSTS or host == public_host(url):
                    continue
                official_domain = next(
                    (
                        domain
                        for domain in sorted(trusted)
                        if host == domain or host.endswith("." + domain)
                    ),
                    None,
                )
                status = "trusted_candidate" if official_domain else "candidate"
                _audit(
                    engine,
                    candidate_url,
                    "public_directory",
                    status,
                    {
                        "directory_url": url,
                        "official_domain": official_domain,
                        "discovered_host": host,
                    },
                )
                stats["candidates_found"] += 1
                if official_domain:
                    candidates.append(
                        {
                            "name": official_domain,
                            "careers_url": candidate_url,
                            "official_domain": official_domain,
                            "provenance": {"method": "public_directory", "url": url},
                        }
                    )
        except (DiscoveryError, ValueError, AttributeError) as exc:
            _audit(
                engine,
                url if isinstance(url, str) else "",
                "public_directory",
                "failed",
                {
                    "error": str(exc)
                    if isinstance(exc, DiscoveryError)
                    else "invalid_directory"
                },
            )
            stats["failed"] += 1
    return candidates


def discover(
    engine: Engine,
    candidates_path: str | Path,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict:
    """Scan configured official pages, without making search requests by default.

    A JSON list contains operator-confirmed employer pages: name, careers_url,
    optional official_domain. A config object accepts candidates plus optional
    search settings. Unknown search domains are audited for later confirmation;
    search.trusted_domains explicitly authorizes their official-page association.
    Imported pages must be on the declared official domain or its subdomains.
    """
    try:
        config = json.loads(Path(candidates_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DiscoveryError("invalid_candidates_file") from None
    if isinstance(config, list):
        config = {"candidates": config}
    if not isinstance(config, dict) or not isinstance(
        config.get("candidates", []), list
    ):
        raise DiscoveryError("invalid_candidates_file")
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise DiscoveryError("timezone_required")
    key = (
        "discovery-cursor:"
        + sha256(str(Path(candidates_path).resolve()).encode()).hexdigest()[:24]
    )
    if client is None:
        with httpx.Client(transport=PublicTransport(), trust_env=False) as owned:
            return _discover(engine, config, owned, key, now)
    return _discover(engine, config, client, key, now)


def _discover(
    engine: Engine, config: dict, client: httpx.Client, key: str, now: datetime
) -> dict:
    stats = {
        "checked": 0,
        "registered": 0,
        "duplicates": 0,
        "failed": 0,
        "candidates_found": 0,
        "search_queries": 0,
        "employers_added": 0,
        "sources_added": 0,
    }
    fetcher = Fetcher(client)
    candidates = list(config.get("candidates", []))
    candidates.extend(_search_candidates(engine, config, fetcher, stats, key, now))
    candidates.extend(_directory_candidates(engine, config, fetcher, stats, key, now))
    seen = set()
    # Cap each run even when an imported file or search result set is enormous.
    max_candidates = config.get("max_candidates", 100)
    if not isinstance(max_candidates, int) or not 1 <= max_candidates <= 1000:
        raise DiscoveryError("invalid_candidate_budget")
    stats["deferred"] = max(0, len(candidates) - max_candidates)
    indices = reserve_batch(
        engine, key + ":candidates", len(candidates), max_candidates, now
    )
    for candidate in (candidates[index] for index in indices):
        url = candidate.get("careers_url", "") if isinstance(candidate, dict) else ""
        if not isinstance(url, str):
            url = ""
        if url in seen:
            continue
        seen.add(url)
        stats["checked"] += 1
        try:
            if (
                not isinstance(candidate, dict)
                or not isinstance(candidate.get("name"), str)
                or not candidate["name"].strip()
            ):
                raise DiscoveryError("invalid_candidate")
            host = public_host(url)
            domain = normalize_domain(candidate.get("official_domain") or host)
            if host in ATS_HOSTS or not (host == domain or host.endswith("." + domain)):
                raise DiscoveryError("unconfirmed_official_association")
            careers_url, links = _find_careers_source(engine, fetcher, url, domain)
            if not links:
                raise DiscoveryError("no_supported_source")
            if careers_url != url:
                candidate = {
                    **candidate,
                    "careers_url": careers_url,
                    "provenance": {
                        "method": "official_careers_navigation",
                        "seed_url": url,
                        "source": candidate.get("provenance", "confirmed_import"),
                    },
                }
                url = careers_url
            confirmed = []
            for provider, token, board_url in links[:10]:
                with Session(engine) as session:
                    existing = session.execute(
                        select(JobSource, Employer.official_domain)
                        .join(Employer, Employer.id == JobSource.employer_id)
                        .where(
                            JobSource.provider == provider,
                            JobSource.board_identifier == token,
                        )
                    ).first()
                if existing is not None:
                    source, owner_domain = existing
                    if owner_domain != domain:
                        _audit(
                            engine,
                            url,
                            "public_board_check",
                            "failed",
                            {
                                "provider": provider,
                                "board_identifier": token,
                                "error": "source_employer_conflict",
                            },
                        )
                        stats["failed"] += 1
                        continue
                    if source.status == "validated":
                        # The current official page still links to the already
                        # validated board. Polling owns its subsequent health.
                        confirmed.append((provider, token, board_url))
                        continue
                try:
                    make_collector(provider, client).fetch_jobs(token)
                except CollectorError as exc:
                    _audit(
                        engine,
                        url,
                        "public_board_check",
                        "failed",
                        {
                            "provider": provider,
                            "board_identifier": token,
                            "error": exc.code,
                        },
                    )
                    stats["failed"] += 1
                else:
                    confirmed.append((provider, token, board_url))
            if confirmed:
                added, duplicates, employers_added = _register(
                    engine, candidate, domain, confirmed
                )
                stats["registered"] += added
                stats["sources_added"] += added
                stats["employers_added"] += employers_added
                stats["duplicates"] += duplicates
                if not added:
                    _audit(
                        engine,
                        url,
                        "official_careers_link",
                        "duplicate",
                        {
                            "sources": duplicates,
                            "boards": [
                                {"provider": provider, "board_identifier": token}
                                for provider, token, _ in confirmed
                            ],
                            "official_domain": domain,
                            "provenance": candidate.get(
                                "provenance", "confirmed_import"
                            ),
                        },
                    )
        except (DiscoveryError, ValueError) as exc:
            _audit(
                engine,
                url,
                "official_careers_link",
                "failed",
                {
                    "error": str(exc)
                    if isinstance(exc, DiscoveryError)
                    else "invalid_candidate"
                },
            )
            stats["failed"] += 1
    with Session(engine) as session:
        stats["employers_total"] = session.scalar(
            select(func.count()).select_from(Employer)
        )
        stats["sources_total"] = session.scalar(
            select(func.count()).select_from(JobSource)
        )
    _audit(
        engine, "", "discovery_run", "complete", {**stats, "run_at": now.isoformat()}
    )
    return stats
