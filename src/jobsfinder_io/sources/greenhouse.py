"""Bounded public Greenhouse GET requests and provider-specific normalization."""

import hashlib
import html
import json
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

API_ROOT = "https://boards-api.greenhouse.io/v1/boards"
TIMEOUT = httpx.Timeout(15, connect=5)


class CollectorError(Exception):
    """A sanitized poll error, never a raw response or exception message."""

    def __init__(
        self,
        code: str,
        *,
        status: str = "failed",
        http_status: int | None = None,
        post_count: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.http_status = http_status
        self.post_count = post_count


@dataclass(frozen=True)
class GreenhouseJob:
    external_posting_id: str
    external_requisition_id: str | None
    title: str
    canonical_job_url: str
    apply_url: str
    description_text: str
    source_updated_at: datetime | None
    content_hash: str
    source_published_at: datetime | None = None
    date_provenance: str = "unknown:greenhouse.first_published_not_checked"
    locations: str = ""


class _DescriptionParser(HTMLParser):
    blocks = {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "tr",
        "section",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        if not self.ignored and tag in self.blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        if not self.ignored and tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def normalize_description(content: str) -> str:
    # Greenhouse may entity-encode the HTML, sometimes through two layers.
    for _ in range(2):
        content = html.unescape(content)
    parser = _DescriptionParser()
    parser.feed(content)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp lacks timezone")
    return result.astimezone(UTC)


def _post_id(value: object) -> str:
    # Greenhouse post IDs are positive integers, unlike internal job IDs.
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid post ID")
    return str(value)


def _normalize_job(raw: object) -> GreenhouseJob:
    if not isinstance(raw, dict):
        raise ValueError("Invalid listing")
    identity = _post_id(raw.get("id"))
    title, content, link = raw.get("title"), raw.get("content"), raw.get("absolute_url")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Missing title")
    if not isinstance(content, str) or not isinstance(link, str):
        raise ValueError("Missing description or URL")
    url = urlsplit(link)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or any(char.isspace() or ord(char) < 32 for char in link)
    ):
        raise ValueError("Invalid posting URL")
    _ = url.port
    requisition = raw.get("requisition_id")
    if requisition is not None and not isinstance(requisition, str):
        raise ValueError("Invalid requisition ID")
    title = " ".join(title.split())
    description = normalize_description(content)
    location = raw.get("location") or {}
    if not isinstance(location, dict) or not isinstance(location.get("name", ""), str):
        raise ValueError("Invalid location")
    locations = " ".join(location.get("name", "").split())
    digest = hashlib.sha256(
        json.dumps(
            [title, description, link, requisition, locations], ensure_ascii=False
        ).encode()
    ).hexdigest()
    return GreenhouseJob(
        external_posting_id=identity,
        external_requisition_id=requisition,
        title=title,
        canonical_job_url=link,
        apply_url=link,
        description_text=description,
        source_updated_at=parse_timestamp(raw.get("updated_at")),
        content_hash=digest,
        locations=locations,
    )


class GreenhouseCollector:
    def __init__(
        self,
        client: httpx.Client,
        *,
        request_interval: float = 1,
        sleep: Callable[[float], None] = time.sleep,
        max_response_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.client = client
        self.request_interval = request_interval
        self.sleep = sleep
        self.max_response_bytes = max_response_bytes
        self.last_http_status: int | None = None
        self._last_request: float | None = None

    @staticmethod
    def _board_url(token: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise CollectorError("invalid_board_token")
        return f"{API_ROOT}/{token}/jobs"

    def _get_json(self, url: str) -> object:
        for attempt in range(3):
            if self._last_request is not None:
                delay = self.request_interval - (time.monotonic() - self._last_request)
                if delay > 0:
                    self.sleep(delay)
            self._last_request = time.monotonic()
            self.last_http_status = None
            retry_after = 0.0
            try:
                with self.client.stream(
                    "GET",
                    url,
                    timeout=TIMEOUT,
                    follow_redirects=False,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "JobsFinder.io/0.1 (personal public-board monitor)",
                    },
                ) as response:
                    self.last_http_status = response.status_code
                    if response.status_code == 200:
                        body = bytearray()
                        for chunk in response.iter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > self.max_response_bytes:
                                raise CollectorError(
                                    "response_too_large", http_status=200
                                )
                        try:
                            return json.loads(body)
                        except (ValueError, UnicodeError, RecursionError) as exc:
                            raise CollectorError(
                                "invalid_json", http_status=200
                            ) from exc
                    error = CollectorError(
                        f"http_{response.status_code}", http_status=response.status_code
                    )
                    if (
                        response.status_code != 429
                        and not 500 <= response.status_code <= 599
                    ):
                        raise error
                    retry_after = self._retry_after(response.headers.get("Retry-After"))
            except httpx.RequestError as exc:
                code = (
                    "timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "network_error"
                )
                error = CollectorError(code, http_status=self.last_http_status)
            if attempt == 2 or retry_after > 60:
                raise error
            self.sleep(max(2**attempt + random.uniform(0, 0.25), retry_after))
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(value: str | None) -> float:
        if value is None:
            return 0
        try:
            return max(0, int(value))
        except ValueError:
            try:
                return max(
                    0,
                    (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(),
                )
            except (ValueError, TypeError, OverflowError):
                return 0

    def fetch_jobs(self, token: str) -> list[GreenhouseJob]:
        payload = self._get_json(f"{self._board_url(token)}?content=true")
        count = None
        try:
            if not isinstance(payload, dict) or not isinstance(
                payload.get("jobs"), list
            ):
                raise ValueError("Missing jobs list")
            raw_jobs = payload["jobs"]
            count = len(raw_jobs)
            meta = payload.get("meta")
            if not isinstance(meta, dict) or type(meta.get("total")) is not int:
                raise ValueError("Missing total")
            if meta["total"] != count:
                raise ValueError("Incomplete jobs list")
            jobs = [_normalize_job(raw) for raw in raw_jobs]
            if len({job.external_posting_id for job in jobs}) != len(jobs):
                raise ValueError("Duplicate post IDs")
            return jobs
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise CollectorError(
                "invalid_or_incomplete_jobs",
                status="partial",
                http_status=200,
                post_count=count,
            ) from exc

    def enrich_publication(self, token: str, job: GreenhouseJob) -> GreenhouseJob:
        payload = self._get_json(f"{self._board_url(token)}/{job.external_posting_id}")
        try:
            if (
                not isinstance(payload, dict)
                or _post_id(payload.get("id")) != job.external_posting_id
            ):
                raise ValueError("Detail identity mismatch")
            published = parse_timestamp(payload.get("first_published"))
        except (ValueError, TypeError, OverflowError) as exc:
            raise CollectorError("invalid_job_detail", http_status=200) from exc
        return replace(
            job,
            source_published_at=published,
            date_provenance=(
                "greenhouse.detail.first_published"
                if published
                else "unknown:greenhouse.first_published_absent"
            ),
        )
