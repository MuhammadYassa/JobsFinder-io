# Employer discovery

`discover(engine, candidates_path, *, client=None, now=None)` reads an ignored
private JSON configuration. No Gemini or search account is required for imported
pages or configured public directories. Discovery validates an official employer
page's supported ATS link and complete public board before registration. New
sources start monitoring automatically; their first poll is a baseline, not a
claim of recent publication.

```json
{
  "max_candidates": 50,
  "candidates": [
    {
      "name": "Example employer",
      "careers_url": "https://example.com/careers",
      "official_domain": "example.com"
    }
  ],
  "max_directories": 2,
  "directories": [
    {
      "url": "https://directory.example/members",
      "max_links": 100,
      "trusted_domains": ["example.com"]
    }
  ]
}
```

A plain candidate list remains supported. Importing a candidate asserts the
named employer owns its page; verify this first. A directory's links establish
candidate discovery only. Unknown domains are persisted as
`DiscoveryAttempt(status="candidate", method="public_directory")` and are never
followed automatically. After confirming ownership, add the official employer
career page to `candidates`, or confirm its domain in that directory's
`trusted_domains`. Directory candidates use their confirmed domain as the
employer name. Direct directory links to ATS boards cannot prove ownership and
are ignored. Only configured directory pages are read; there is no unrestricted
crawler or automatic approval of unknown domains.

Candidate pages, directory pages and bounded directory link batches use durable
SQLite cursors. Repeated daily runs advance through the remaining queue instead
of always checking the same initial employers. A failed or interrupted batch is
retried on the next complete queue cycle. The cursor is scoped to the resolved
configuration path; keep that path stable across runs. A currently linked board
already validated for the same employer avoids another feed download; regular
monitoring owns its later health. Association conflicts are recorded as failures.

Optional search requires an explicitly configured provider and its API key:

```json
{
  "candidates": [],
  "search": {
    "provider": "brave",
    "max_queries": 2,
    "rotate_breadth": true,
    "queries": ["regional manufacturing employer careers Germany"],
    "trusted_domains": []
  }
}
```

Leave `search` absent to avoid paid requests. Set `BRAVE_SEARCH_API_KEY` only if
you intend to enable the provider. Missing credentials return
`search_skipped: missing_credentials`; imports/directories continue. Explicit
queries precede the generated rotation. `rotate_breadth` defaults to false.
Generated queries vary industry and software role while interleaving all 50 US
states/DC and Germany, Ireland, UK, UAE, Canada, Singapore, Netherlands, Sweden,
France, Austria, Switzerland, Australia and New Zealand. Primary countries
receive extra slots. Configurable `us_regions`, `countries` (these ISO codes),
`industries`, and `roles` lists can narrow or customize the rotation. The defaults
include startups, government, universities, insurance, healthcare, manufacturing,
finance, retail, logistics, utilities and consulting, and junior/graduate,
backend, full-stack, .NET, Java/Python, integration, developer-tools and applied
AI software roles. Query work also uses a durable cursor. Brave's restricted
country-filter markets use `fallback_country` (default US) for IE/AE/SG, retaining
the actual target country in the query; this can affect geographic ranking.

Search results on unknown domains remain review candidates. Snippets and public
directory membership do not prove employer ownership. Search `trusted_domains`
only allows already confirmed employer domains. See the documented
[Brave Web Search interface](https://api-dashboard.search.brave.com/api-reference/web/search/get).

**Coverage limit:** without search credentials, expansion is limited to supplied
candidate pages and confirmed domains linked by configured directories. Once
these finite queues are exhausted, reruns verify known sources and retain unknown
candidates for review; they cannot discover arbitrary new employers. A search
provider expands candidate discovery but still needs ownership confirmation.
Rotating queries specify intended scope, not verified coverage of every market.

Returned counts include `registered`/`sources_added`, `employers_added`, current
`employers_total`/`sources_total`, checked pages, duplicates, failed checks,
candidates found, search queries, directories checked and deferred candidate
pages. `DiscoveryAttempt` retains checks, failures, registered provider/board IDs,
source provenance, and run totals. Registry mutations are serialized and network
calls run outside database transactions.

Public HTTPS checks block local/private networks, credentials and custom ports.
The transport pins public DNS addresses and retains TLS verification. Cross-host
redirects are refused. Responses are capped at 2 MB; requests have 15-second
timeouts, three attempts and at least one-second spacing. Robots denial or an
unavailable robots file (except 404) blocks the page. Directory budgets are at
most 20 pages/run and 1000 links/page; candidates are capped at 100/run by default
and at most 1000. JavaScript-only and unsupported ATS pages require another
supported integration; access controls are never bypassed.

Learning checkpoint: trace `discover()` to `reserve_batch()`, career-page/robots
checks, ATS validation, and `_register()`. The cursor records what to try next;
`DiscoveryAttempt` records what was actually checked; registry records are added
only after validated employer association and successful public-board access.
