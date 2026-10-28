"""Public HTTPS requests with DNS pinning, robots rules and bounded resources."""

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "JobsFinder/1.0"
MAX_BYTES = 2_000_000


class DiscoveryError(ValueError):
    """A sanitized discovery failure safe for persistent operational history."""


def public_host(url: str) -> str:
    """Reject credentials, custom ports, local names and non-public IP literals."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.fragment
            or any(c.isspace() for c in url)
        ):
            raise DiscoveryError("unsafe_url")
        host = host.encode("idna").decode("ascii").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".local", ".localhost", ".internal")):
                raise DiscoveryError("unsafe_host") from None
        else:
            if not address.is_global:
                raise DiscoveryError("non_public_address")
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, DiscoveryError):
            raise
        raise DiscoveryError("unsafe_url") from None
    return host


def resolve_public(host: str) -> str:
    """Every returned address must be public; pin one for the actual connection."""
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise DiscoveryError("dns_failed") from None
    ips = {item[4][0] for item in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise DiscoveryError("non_public_address")
    return sorted(ips)[0]


class PublicTransport(httpx.BaseTransport):
    """Connect to the inspected IP while verifying TLS against the original host.

    Resolving only before httpx's ordinary request would leave a DNS-rebinding
    gap. The rewritten connection URL pins the validated address. SNI and Host
    retain the original domain. Redirects are handled by Fetcher and revalidated.
    """

    def __init__(self) -> None:
        self.transport = httpx.HTTPTransport(retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = public_host(str(request.url))
        address = resolve_public(host)
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return self.transport.handle_request(pinned)

    def close(self) -> None:
        self.transport.close()


class Fetcher:
    def __init__(self, client: httpx.Client, *, spacing: float = 1.0) -> None:
        self.client = client
        self.spacing = spacing
        self.last_request = 0.0
        self.robots: dict[str, RobotFileParser] = {}

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict | None = None,
        allow_redirects: bool = True,
    ) -> httpx.Response:
        original_host = public_host(url)
        # MockTransport is explicitly injected for offline tests. Production's
        # PublicTransport performs the DNS check on the actual connection.
        if not isinstance(self.client._transport, PublicTransport):
            resolve_public(original_host)
        for redirect in range(4):
            public_host(url)
            response = self._request(url, headers=headers, params=params)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            if not allow_redirects or redirect == 3:
                raise DiscoveryError("redirect_refused")
            next_url = urljoin(url, response.headers.get("location", ""))
            # Official-page evidence must remain on its asserted official host;
            # no API credential can be forwarded to another host either.
            if public_host(next_url) != original_host or next_url == url:
                raise DiscoveryError("cross_host_redirect")
            url, params = next_url, None
        raise DiscoveryError("redirect_limit")

    def _request(self, url: str, *, headers: dict | None, params: dict | None):
        for attempt in range(3):
            wait = self.spacing - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            try:
                with self.client.stream(
                    "GET",
                    url,
                    headers={"User-Agent": USER_AGENT, **(headers or {})},
                    params=params,
                    timeout=httpx.Timeout(15, connect=5),
                    follow_redirects=False,
                ) as streamed:
                    chunks = []
                    size = 0
                    for chunk in streamed.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise DiscoveryError("response_too_large")
                        chunks.append(chunk)
                    # iter_bytes() has already decompressed the entity. Keeping
                    # the original encoding header would decode it again when
                    # constructing the buffered response (and fail on gzip).
                    decoded_headers = {
                        key: value
                        for key, value in streamed.headers.items()
                        if key.lower() not in {"content-encoding", "content-length"}
                    }
                    response = httpx.Response(
                        streamed.status_code,
                        headers=decoded_headers,
                        content=b"".join(chunks),
                        request=streamed.request,
                    )
            except httpx.RequestError:
                if attempt == 2:
                    raise DiscoveryError("request_failed") from None
            else:
                if response.status_code not in {429, 500, 502, 503, 504}:
                    return response
                if attempt == 2:
                    raise DiscoveryError(f"http_{response.status_code}")
                # A longer provider delay ends this pass instead of retrying
                # before Retry-After permits it.
                delay = response.headers.get("retry-after", "")
                if delay and (not delay.isdecimal() or int(delay) > 30):
                    raise DiscoveryError("retry_later")
                if delay:
                    time.sleep(int(delay))
            time.sleep(2**attempt)
        raise DiscoveryError("request_failed")

    def career_page(self, url: str) -> str:
        host = public_host(url)
        if host not in self.robots:
            robots_url = f"https://{host}/robots.txt"
            response = self.get(robots_url)
            if response.status_code == 404:
                lines = []
            elif response.status_code == 200:
                lines = response.text.splitlines()
            else:
                raise DiscoveryError("robots_unavailable")
            robot = RobotFileParser(robots_url)
            robot.parse(lines)
            self.robots[host] = robot
        robot = self.robots[host]
        if not robot.can_fetch(USER_AGENT, url):
            raise DiscoveryError("robots_disallowed")
        crawl_delay = float(robot.crawl_delay(USER_AGENT) or 0)
        if crawl_delay > 30:
            raise DiscoveryError("crawl_delay_exceeds_budget")
        self.spacing = max(self.spacing, crawl_delay)
        response = self.get(url)
        if response.status_code != 200:
            raise DiscoveryError(f"http_{response.status_code}")
        if "text/html" not in response.headers.get("content-type", ""):
            raise DiscoveryError("not_html")
        return response.text
