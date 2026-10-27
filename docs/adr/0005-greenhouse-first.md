# ADR 0005 — Implement Greenhouse as the first ATS adapter

- **Status:** Accepted — approved by project owner
- **Date:** 2026-10-27

## Context

A first collector is necessary to validate the entire discover → store → compare pipeline against a documented employer-specific public feed. Supporting several ATS platforms at once would make debugging and data modeling harder.

## Options

1. **Greenhouse public Job Board API first**: documented public GET listings and stable source-specific posting IDs.
2. Lever or Ashby first: legitimate alternatives, deferred to subsequent adapters.
3. Universal browser scraper first: difficult to generalize reliably, and more operationally fragile.

## Decision

The first production-like adapter will be Greenhouse. Begin with an explicitly validated company board identifier and read-only public listings. Treat its `updated_at` as an update indicator, not evidence of original posting date. Implement source completeness and provenance safeguards before any closure logic.

## Consequences and boundaries

- Phase 1 only models/employer source persistence; actual HTTP fetching starts in Phase 2.
- An employer does not equal a single ATS: the model must support multiple sources per employer.
- No claim of full-market coverage: only the sources we have validated and registered are monitored.
- General adapters and employer discovery are later phases.
