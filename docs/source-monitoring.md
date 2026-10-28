# Source Discovery and Monitoring Strategy (Proposed v0.1)

> Current implementation: Greenhouse, Lever global/EU and Ashby adapters,
> source polling/reconciliation, candidate discovery and optional Brave search
> are implemented. See [ADR 0008](adr/0008-integrated-personal-workflow.md) and
> [discovery configuration](../src/jobsfinder_io/discovery/README.md).

## Purpose

Detect newly visible jobs from **employer-owned or employer-controlled public listings** earlier than search-index-only workflows. Maintain a broad backfill path for employers not yet monitored. There is no universal Greenhouse/Lever/Ashby endpoint that lists all companies.

## Initial public-source adapters

| ATS | Official docs | Proposed first approach | Freshness caveat |
| --- | --- | --- | --- |
| Greenhouse | [Job Board API](https://docs.greenhouse.io/job-board.html) | GET an employer's public board jobs using its board token; optionally request full content | `updated_at` describes updates, not necessarily initial publication |
| Lever | [Postings API](https://github.com/lever/postings-api) | GET an employer's public postings; paginate as documented and support relevant regional host | Do not assume a field is original publication without validation |
| Ashby | [Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) | GET an employer's job-board posts | `publishedAt` is most recent publication, including potential republication |
| Others (Workday, iCIMS, custom) | Research each separately | Later: explicit supported integration, public feeds or permitted read-only pages | No universal anonymous public API; many require custom adapters |

## Employer registry workflow

1. Discover employer from official website, public job board, search discovery or other reliable source.
2. Record employer website, origin evidence, ATS provider and public board identifier/URL.
3. Validate employer-to-board association and readable endpoint (read-only GET); reject unresolved/untrusted links.
4. Promote candidate into `job_sources` with an auditable validation note.
5. Run a complete baseline scan. Queue old visible jobs as `baseline` separately from incremental discoveries.

## Polling policy

- Proposed default: **60 minutes** for validated supported public sources, adjustable by provider/source.
- Respect robots/terms as applicable, provider rate limits, usage policies and site availability; use timeouts, bounded concurrency and backoff for 429/5xx responses.
- Collect all required pages, or mark scan partial. No absence/closure inference from partial or failed scans.
- Handle overlapping runs safely (lock/lease or serialized source jobs).
- Use HTTP caching/conditional requests only when supported and semantics are understood.
- Retry transient errors with jitter; persistent failures affect source health status, not vacancy status.

## New/changed/closed semantics

- Store stable `(source_id, external_posting_id)` keys.
- On first scan: baseline only. Subsequent healthy scans: new IDs become `incremental` discoveries.
- Hash normalized meaningful content to identify changed descriptions or locations without triggering on nonsemantic formatting where possible.
- Missing IDs from complete snapshots indicate possibly removed jobs, subject to closure policy.
- Reappearances retain history and may warrant a fresh notification if material and permitted by reporting history.
- Unknown publication dates remain unknown. Search-engine discovery times and employer `updated_at` values do not prove dates.

## Broad source discovery (later milestone)

- Search official employer careers, employer-specific ATS boards, public graduate program directories and allowed job discovery pages.
- Rotate **industries, employer sizes, US regions, and international countries**; avoid only large tech firms and major job boards.
- Validate new employer + source pairs before inclusion. Record successful and failed validation attempts to avoid repeated rediscovery.
- Diversify source discovery to find employers missing from existing feeds; don't assume every employer has a usable public API.
- Search-query APIs may cost more and lag real employer publication; separate costs/metrics from direct monitoring.

## Measurement

Report: validated vs. merely discovered sources; healthy polls; source failures; unique incremental job IDs; percentage screened; observed detection lag against trustworthy timestamps; and false-positive/repost rates. A one-hour poll aims for near-hourly visibility **only after** the public employer feed exposes the post.

## Research to validate during implementation

- Check official provider schemas/current access before writing an adapter (fields and hosts can change).
- Test pagination and whether each provider response is exhaustive for a board.
- For Greenhouse, distinguish job-post ID from internal requisition ID.
- For Ashby, store recent `publishedAt` with its exact semantics, not as incontrovertible original publish time.
- For Lever, inspect host/region differences and actual source payloads rather than assuming fields match other providers.
