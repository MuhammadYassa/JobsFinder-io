# Development Roadmap (Planning v0.3)

**Guideline:** Small slices, demonstrable behavior, meaningful tests. Phases 1–3 are implemented; unchecked items remain planned. Every phase requires owner approval before coding.

## Phase 0 — Design and guardrails

- [ ] Review/approve scope, core architecture and remaining proposed decisions in `docs/adr/`.
- [x] Approve modular monolith, SQLite-first storage, and Greenhouse-first integration (ADRs 0001, 0004, 0005).
- [x] Approve SQLAlchemy 2.x + Alembic and exactly four initial tables: `employers`, `job_sources`, `postings`, `poll_runs` (ADR 0006).
- [ ] Add root `AGENTS.md` and project docs; update only generic README links if approved.
- [ ] Agree on initial source/identity rules and baseline semantics.
- [ ] Decide local DB and notification channel for MVP.

**Exit:** Owner accepts core design; docs and development protocol in place.

## Phase 1 — Registry and local persistence

Phase 1 is implemented; see the [registry code](../src/jobsfinder_io/registry.py), models, migrations, and root README. The earlier Phase 1 design file is absent from this checkout.


- [x] Define typed employer, source, posting and poll-run entities.
- [x] Implement SQLAlchemy 2.x ORM models and SQLite session/transaction handling for the four approved tables.
- [x] Configure Alembic and create/test the initial four-table migration.
- [x] Add CLI commands to add/list/validate sources and inspect jobs.
- [x] Persist UTC timestamps and source identity safely, with unique constraints.

**Exit:** Employer+source records survive restart; duplicate registrations are prevented; CLI and persistence tested without network.

## Phase 2 — First ATS collector and baseline monitoring

See the approved [Phase 2 design and implementation notes](phase-2-greenhouse-design.md).

- [x] Implement a read-only **Greenhouse Job Board API** collector.
- [x] Normalize listings and preserve source IDs, links, source timestamps, and date provenance in the existing fields. Raw JSON retention is deferred because the approved schema has no snapshot field.
- [x] Define complete/incomplete poll results, retries, timeouts, and initial baseline.
- [x] Implement new/updated/missing/reappeared state comparison.
- [x] Write fixture-based regression tests.

**Exit:** Two repeated scans are idempotent; a synthetic new ID is identified exactly once; failed fetch does not close jobs.

## Phase 3 — Docker and GitHub Actions CI

The owner revised this phase to local container packaging and CI. See
[ADR 0007](adr/0007-docker-and-ci.md) and the root README for usage.

- [x] Build a Python/uv image with locked application dependencies and a non-root runtime.
- [x] Add one Compose service with an existing host-directory mount for SQLite.
- [x] Support explicit Alembic migrations and all existing CLI commands inside containers.
- [x] Exclude local data, secrets, virtual environments, and unrelated files from build context.
- [x] Configure CI for main pushes and pull requests: locked install, all offline tests, Ruff, image build, and container smoke checks.

**Exit:** Docker/CI configuration is in place; local validation results are reported
in the implementation handoff. No image publishing or deployment is configured.

## Deferred — More employer sources and scheduled polling

These were the previous Phase 3 proposal and are outside the approved Docker/CI
slice. They still require separate authorization.

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
