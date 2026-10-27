# ADR 0003 — Use AI for interpretation, not basic monitoring

- **Status:** Proposed — awaiting owner approval
- **Date:** 2026-10-27

## Context

Identifying new provider IDs is deterministic. Judging whether a role is software-heavy, junior-accessible or visa-compatible requires nuanced interpretation of job descriptions. Continuous autonomous browsing by AI for every source would be costly and difficult to audit.

## Options

1. AI agents own discovery, polling, deduplication and screening: flexible, but duplicated work, unstable state, high cost.
2. **Deterministic collection/change detection + conservative prefilter + structured AI eligibility reviewer:** auditable, inexpensive, testable; AI only on new/changed candidates.
3. Keywords only: inexpensive but likely to miss unusual job titles and nuanced eligibility.

## Proposed choice

Option 2. Use explicit schema-validated AI responses with evidence, model/prompt/policy version and `needs_review` state. Separate US/international policy. False negatives matter more than retaining a few uncertain leads. Give fast alerts priority; generate cover letters later from verified facts, independent of monitoring throughput.

## Consequences

- Positive: lower recurring costs, traceability, ability to evaluate false negatives, easier fallback when AI API unavailable.
- Tradeoff: requires a curated evaluation set, unknown outcomes and manual reviews; legal/work-authorization decisions cannot be guaranteed by LLM output.
- Revisit when: measured false-negative rate or unexpected processing latency makes this insufficient.
