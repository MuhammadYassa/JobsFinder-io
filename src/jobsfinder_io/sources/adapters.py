"""Public ATS adapters and the small registry of supported provider interfaces.

References: https://github.com/lever/postings-api and
https://developers.ashbyhq.com/docs/public-job-posting-api
Only GET interfaces are implemented; application submission is intentionally absent.
"""

import hashlib
import json
import re
from urllib.parse import urlencode, urlsplit

import httpx

from jobsfinder_io.sources.greenhouse import (
    CollectorError,
    GreenhouseCollector,
    GreenhouseJob,
    normalize_description,
    parse_timestamp,
)

PROVIDERS = ("greenhouse", "lever", "lever_eu", "ashby")


def source_endpoint(provider: str, token: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("Use a board identifier, not a URL")
    roots = {
        "greenhouse": "https://boards-api.greenhouse.io/v1/boards",
        "lever": "https://api.lever.co/v0/postings",
        "lever_eu": "https://api.eu.lever.co/v0/postings",
        "ashby": "https://api.ashbyhq.com/posting-api/job-board",
    }
    if provider not in roots:
        raise ValueError("Unsupported provider")
    return f"{roots[provider]}/{token}" + ("/jobs" if provider == "greenhouse" else "")


def _text(value: object, *, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError("Missing or invalid text")
    return value.strip()


def _url(value: object) -> str:
    link = _text(value, required=True)
    parsed = urlsplit(link)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(c.isspace() or ord(c) < 32 for c in link)
    ):
        raise ValueError("Invalid public URL")
    _ = parsed.port
    return link


def _locations(values: list[object]) -> str:
    return "; ".join(
        sorted({_text(value) for value in values if value is not None} - {""})
    )


def _job(
    identity: str,
    title: str,
    link: str,
    apply: str,
    description: str,
    locations: str,
    *,
    updated=None,
    provenance: str,
) -> GreenhouseJob:
    digest = hashlib.sha256(
        json.dumps(
            [title, link, apply, description, locations], ensure_ascii=False
        ).encode()
    ).hexdigest()
    return GreenhouseJob(
        external_posting_id=identity,
        external_requisition_id=None,
        title=title,
        canonical_job_url=link,
        apply_url=apply,
        description_text=description,
        source_updated_at=updated,
        content_hash=digest,
        date_provenance=provenance,
        locations=locations,
    )


class LeverCollector(GreenhouseCollector):
    """Bounded offset pagination; every page must validate before reconciliation."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        region: str = "global",
        page_size: int = 100,
        max_pages: int = 100,
        **kwargs,
    ) -> None:
        super().__init__(client, **kwargs)
        if region not in {"global", "eu"} or page_size < 1 or max_pages < 1:
            raise ValueError("Invalid Lever pagination/region")
        self.provider = "lever_eu" if region == "eu" else "lever"
        self.page_size = page_size
        self.max_pages = max_pages

    def fetch_jobs(self, token: str) -> list[GreenhouseJob]:
        try:
            endpoint = source_endpoint(self.provider, token)
        except ValueError as exc:
            raise CollectorError("invalid_board_token") from exc
        jobs: list[GreenhouseJob] = []
        seen: set[str] = set()
        for page in range(self.max_pages):
            params = urlencode(
                {"mode": "json", "skip": page * self.page_size, "limit": self.page_size}
            )
            payload = self._get_json(f"{endpoint}?{params}")
            try:
                if not isinstance(payload, list) or len(payload) > self.page_size:
                    raise ValueError("Invalid page")
                for raw in payload:
                    job = self._normalize(raw)
                    if job.external_posting_id in seen:
                        raise ValueError("Repeated identity across pages")
                    seen.add(job.external_posting_id)
                    jobs.append(job)
            except (ValueError, TypeError, OverflowError) as exc:
                raise CollectorError(
                    "invalid_or_incomplete_jobs",
                    status="partial",
                    http_status=200,
                    post_count=len(jobs),
                ) from exc
            if len(payload) < self.page_size:
                return jobs
        raise CollectorError(
            "pagination_budget_exhausted",
            status="partial",
            http_status=200,
            post_count=len(jobs),
        )

    @staticmethod
    def _normalize(raw: object) -> GreenhouseJob:
        if not isinstance(raw, dict):
            raise ValueError("Invalid listing")
        identity = _text(raw.get("id"), required=True)
        title = _text(raw.get("text"), required=True)
        categories = raw.get("categories", {})
        if not isinstance(categories, dict):
            raise ValueError("Invalid categories")
        places = categories.get("allLocations", [])
        if not isinstance(places, list):
            raise ValueError("Invalid locations")
        locations = _locations(
            [*places, categories.get("location"), raw.get("country")]
        )
        if raw.get("workplaceType"):
            locations = _locations([locations, raw["workplaceType"]])
        description = raw.get("descriptionPlain")
        if description is None or (
            isinstance(description, str) and not description.strip()
        ):
            description = normalize_description(_text(raw.get("description")))
        else:
            description = _text(description)
        lists = raw.get("lists", [])
        if not isinstance(lists, list):
            raise ValueError("Invalid description lists")
        chunks = [description]
        for item in lists:
            if not isinstance(item, dict):
                raise ValueError("Invalid requirement section")
            chunks.extend(
                [
                    _text(item.get("text")),
                    normalize_description(_text(item.get("content"))),
                ]
            )
        additional = raw.get("additionalPlain")
        if additional is None or (
            isinstance(additional, str) and not additional.strip()
        ):
            additional = normalize_description(_text(raw.get("additional", "")))
        chunks.append(_text(additional))
        return _job(
            identity,
            title,
            _url(raw.get("hostedUrl")),
            _url(raw.get("applyUrl")),
            "\n".join(c for c in chunks if c),
            locations,
            provenance="unknown:lever.public_api_no_publication_time",
        )

    def enrich_publication(self, token: str, job: GreenhouseJob) -> GreenhouseJob:
        return job


class AshbyCollector(GreenhouseCollector):
    def fetch_jobs(self, token: str) -> list[GreenhouseJob]:
        try:
            endpoint = source_endpoint("ashby", token)
        except ValueError as exc:
            raise CollectorError("invalid_board_token") from exc
        payload = self._get_json(endpoint)
        count = None
        try:
            if not isinstance(payload, dict) or not isinstance(
                payload.get("jobs"), list
            ):
                raise ValueError("Missing jobs")
            if payload.get("apiVersion") != "1":
                raise ValueError("Unknown API version")
            raw_jobs = payload["jobs"]
            count = len(raw_jobs)
            jobs = []
            for raw in raw_jobs:
                if not isinstance(raw, dict) or type(raw.get("isListed")) is not bool:
                    raise ValueError("Missing visibility")
                if raw["isListed"]:
                    jobs.append(self._normalize(raw, token))
            if len({j.external_posting_id for j in jobs}) != len(jobs):
                raise ValueError("Duplicate identities")
            return jobs
        except (ValueError, TypeError, OverflowError) as exc:
            raise CollectorError(
                "invalid_or_incomplete_jobs",
                status="partial",
                http_status=200,
                post_count=count,
            ) from exc

    @staticmethod
    def _normalize(raw: dict, token: str) -> GreenhouseJob:
        link = _url(raw.get("jobUrl"))
        parsed = urlsplit(link)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.hostname != "jobs.ashbyhq.com"
            or len(parts) != 2
            or parts[0] != token
        ):
            raise ValueError("Job URL does not belong to board")
        # The documented public API does not promise a separate ID field.
        identity = parts[1]
        description = raw.get("descriptionPlain")
        if description is None or (
            isinstance(description, str) and not description.strip()
        ):
            description = normalize_description(_text(raw.get("descriptionHtml")))
        secondaries = raw.get("secondaryLocations", [])
        if not isinstance(secondaries, list) or any(
            not isinstance(x, dict) for x in secondaries
        ):
            raise ValueError("Invalid locations")
        places = [raw.get("location"), *[x.get("location") for x in secondaries]]
        address = raw.get("address") or {}
        if not isinstance(address, dict):
            raise ValueError("Invalid address")
        postal = address.get("postalAddress") or {}
        if not isinstance(postal, dict):
            raise ValueError("Invalid postal address")
        places.extend([postal.get("addressCountry"), raw.get("workplaceType")])
        return _job(
            identity,
            _text(raw.get("title"), required=True),
            link,
            _url(raw.get("applyUrl")),
            _text(description),
            _locations(places),
            updated=parse_timestamp(raw.get("publishedAt")),
            provenance="ashby.last_published_at:not_original_publication",
        )

    def enrich_publication(self, token: str, job: GreenhouseJob) -> GreenhouseJob:
        return job


def make_collector(
    provider: str, client: httpx.Client, **kwargs
) -> GreenhouseCollector:
    if provider == "greenhouse":
        return GreenhouseCollector(client, **kwargs)
    if provider in {"lever", "lever_eu"}:
        return LeverCollector(
            client, region="eu" if provider == "lever_eu" else "global", **kwargs
        )
    if provider == "ashby":
        return AshbyCollector(client, **kwargs)
    raise ValueError("Unsupported provider")
