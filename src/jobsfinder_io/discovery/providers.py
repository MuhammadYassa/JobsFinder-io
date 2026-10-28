"""Optional configured search; imported official career pages need no paid key.

Brave interface: https://api-dashboard.search.brave.com/api-reference/web/search/get
No search request is made without both a configured provider and credentials.
"""

from typing import Protocol

from jobsfinder_io.discovery.network import DiscoveryError, Fetcher


class SearchProvider(Protocol):
    def search(self, query: str, *, country: str = "US") -> list[dict]: ...


class BraveSearchProvider:
    def __init__(self, fetcher: Fetcher, api_key: str) -> None:
        self.fetcher = fetcher
        self.api_key = api_key

    def search(self, query: str, *, country: str = "US") -> list[dict]:
        if not query.strip() or len(query) > 600 or len(query.split()) > 75:
            raise DiscoveryError("invalid_search_query")
        response = self.fetcher.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": self.api_key},
            params={"q": query, "country": country, "search_lang": "en", "count": 20},
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise DiscoveryError(f"search_http_{response.status_code}")
        try:
            payload = response.json()
            results = payload.get("web", {}).get("results", [])
            if not isinstance(results, list):
                raise ValueError
            return [
                {"name": row["title"], "careers_url": row["url"]}
                for row in results[:20]
                if isinstance(row, dict)
                and isinstance(row.get("url"), str)
                and isinstance(row.get("title"), str)
            ]
        except (ValueError, AttributeError, KeyError, TypeError):
            raise DiscoveryError("search_invalid_response") from None
