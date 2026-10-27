# Development Roadmap (Proposed v0.1)

**Guideline:** Small slices, demonstrable behavior, meaningful tests. Phases describe planned work, not implemented functionality. Every phase requires owner approval before coding.

## Phase 0 — Design and guardrails (current)

- [ ] Review/approve scope, core architecture and decisions in `docs/adr/`.
- [ ] Add root `AGENTS.md` and project docs; update only generic README links if approved.
- [ ] Agree on initial source/identity rules and baseline semantics.
- [ ] Decide local DB and notification channel for MVP.

**Exit:** Owner accepts core design; docs and development protocol in place.

## Phase 1 — Registry and local persistence

- [ ] Define typed employer, source, posting and poll-run entities.
- [ ] Implement SQLite persistence and repository interfaces (migration approach to be decided).
- [ ] Add CLI commands to add/list/validate sources and inspect jobs.
- [ ] Persist UTC timestamps and source identity safely, with unique constraints.

**Exit:** Employer+source records survive restart; duplicate registrations are prevented; CLI and persistence tested without network.

## Phase 2 — First ATS collector and baseline monitoring

- [ ] Implement a read-only **Greenhouse Job Board API** collector.
- [ ] Normalize listings and preserve source IDs, links and original raw evidence.
- [ ] Define complete/incomplete poll results, retries, timeouts, and initial baseline.
- [ ] Implement new/updated/missing/reappeared state comparison.
- [ ] Write fixture-based regression tests.

**Exit:** Two repeated scans are idempotent; a synthetic new ID is identified exactly once; failed fetch does not close jobs.

## Phase 3 — More employer sources and scheduled polling

- [ ] Add Lever and Ashby adapters with provider-specific pagination and field handling.
- [ ] Add scheduler/CLI runner, per-source rate controls, backoff and health tracking.
- [ ] Exercise multi-source deduplication and multiple locations.
- [ ] Record coverage metrics and failed-source visibility.

**Exit:** Scheduled polling detects new postings across three supported providers; source failures don't stop unrelated polls.

## Phase 4 — Screening and evidence

- [ ] Build conservative deterministic relevance checks.
- [ ] Define US and international private search-policy schema.
- [ ] Add typed AI classification with quotes, justification, uncertainty and model/prompt version.
- [ ] Run a labeled evaluation set for false negatives and ambiguous authorization scenarios.
- [ ] Persist results and manual review/override disposition.

**Exit:** New postings are classified reproducibly; AI errors never silently discard jobs; no claims of guaranteed sponsorship.

## Phase 5 — Alerts and actionability

- [ ] Choose notification transport and configure secrets outside Git.
- [ ] Send new high-fit findings promptly with direct links and unresolved-eligibility warnings.
- [ ] Add alert deduplication/retries and suppression for already reported IDs.
- [ ] Add simple CLI shortlist/status updates.

**Exit:** One new suitable posting produces one actionable alert, even across retries and restarts.

## Phase 6 — Automated employer discovery

- [ ] Define discovery candidates and official source-verification workflow.
- [ ] Research accessible search/discovery methods and costs; reject risky/blocked methods.
- [ ] Add providers/regions/industry rotations and new-employer validation.
- [ ] Measure registry growth and useful source coverage, not raw scraped URL count.

**Exit:** Discovery finds a valid previously unknown employer source and begins monitored baseline safely.

## Phase 7 — Reports, backfill and letters

- [ ] Produce 10 AM/8 PM America/New_York US and international digests.
- [ ] Separate newly detected, last-seven-day verified, baseline, freshness-uncertain and rejected jobs.
- [ ] Track historical reporting and materially changed/reopened roles.
- [ ] Generate optional verified, natural-language cover letters only for selected candidates.

**Exit:** Report counts reconcile to stored job dispositions and no known job is repeated without a documented change.

## Phase 8 — Deployment and hardening

- [ ] Choose reliable hosting/database, backup/restore and scheduling approach.
- [ ] Configure structured logs, dashboards or health summaries, budgets and alerting for broken collectors.
- [ ] Test crash recovery, API throttling, missing pages, DB outage and source changes.
- [ ] Set polling frequency using observed coverage and source constraints.

**Exit:** Monitoring operates without a personal computer being online, with observable failures and recoverable state.

## Optional later improvements (not MVP)

- Searchable private web dashboard and application tracker.
- Better employer discovery and source discovery quality scoring.
- Additional ATS adapters, conditional GET and efficient incremental polling where supported.
- Reranking/feedback loops based on manually accepted/rejected results.
- Safe parallelization for many sources and evaluation of different LLM models.

## Cross-phase definition of done

- Scope and acceptance criteria satisfied with an automated regression test.
- No secrets/PII committed; provider access and rate-limiting documented.
- Docs and relevant ADRs updated; tests and formatting checks reported honestly.
- Agent summarizes changed functions, rationale, tradeoffs and a brief code-understanding checkpoint.
- No unsolicited deployment, remote push, job application, or paid action.
