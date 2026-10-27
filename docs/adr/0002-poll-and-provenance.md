# ADR 0002 — Poll verified public employer sources; keep date provenance

- **Status:** Accepted — approved by project owner on 2026-10-27; implementation remains phased
- **Date:** 2026-10-27

## Context

Search-engine listings can surface days after a job appears. Public employer-specific feeds support faster checks of **known boards**, but sources have different timestamps and completeness characteristics, and first discovery is not original publication.

## Options

1. Search-engine/aggregator queries only: simple discovery, incomplete and indexed with delay.
2. **Direct public ATS source polling + independent employer discovery/backfill:** prompt detection for monitored employers, broader coverage growth.
3. Unrestricted browser scraping of all pages: expensive, brittle, and risks violating site policies.

## Decision

Option 2. Initially support official public Greenhouse/Lever/Ashby board feeds. Poll healthy validated sources roughly hourly with source-specific limits and backoff. Store `(source_id, external_posting_id)` as the core identity. Treat first successful scan as baseline; never confuse updates, search crawls or first-seen dates with verified original posting dates. Absence inferred only from successful complete scans under a documented closure policy.

## Consequences

- Positive: efficient detection, interpretable audit history and lower AI usage.
- Tradeoff: coverage limited by monitored employers and public access; discovery work is required. Some providers supply only last-publication or updated timestamps.
- Revisit when: adapters require login, source restrictions prohibit monitoring, volume/availability changes, or evidence shows a more reliable legal source for an ATS.
