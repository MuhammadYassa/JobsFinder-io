# JobsFinder.io — Documentation Index

**Project state:** Integrated personal workflow implemented under the owner's complete-system request. See [ADR 0008](adr/0008-integrated-personal-workflow.md), [deployment](deployment.md), [QA review](qa-review.md), and [build progress](build-plan.md). Earlier design documents retain historical proposals; ADR 0008 supersedes deferred-scope statements. [Final non-AI verification](non-ai-final-verification.md) confirms real monitoring/discovery and one accepted Gmail test. Cloud hosting and AI activation remain unverified.

Current AI provider: [Google Gemini via the official GenAI SDK](adr/0009-gemini-screening.md),
default `gemini-3.5-flash-lite`. Older OpenAI references in build/review records describe
the pre-migration implementation.

The [final ten-job pilot](activation-pilot.md) passed; Gemini defaults to enabled
with a conservative20-call application budget. No permanent schedule or cloud
host is active. SMTP alerts, seven-day reports, hourly polling and daily discovery
continue independently of Gemini. See
[non-AI verification](non-ai-verification.md) and [deployment](deployment.md).

[Completed Flash-Lite accuracy evaluation](flash-lite-final-accuracy.md): all30jobs /
37policy outcomes verified; source-proof gates correct raw false rejections.
That evaluation kept AI disabled; the later final pilot approved enabled configuration. Independent
eligibility/rejection decisions are not accepted.

[Multi-job Gemini screening](gemini-batch-screening.md) adds a durable queue,
token-aware batches and separate 09:30/19:30 New York sessions. Current activation
and limits are documented in the final pilot; earlier verification records below
retain their historical disabled states.

[Flash-Lite live verification](flash-lite-live-verification.md): one five-job
batch succeeded with 10 stored policy results and zero-call cache reuse. Larger
accuracy testing is still needed; evidence-coverage concerns remain. Scheduled
AI stays disabled. [ADR0011](adr/0011-flash-lite-screening.md) records the switch
and supplied 500 RPD / 15 RPM / 250000 TPM limits.

[Live Gemini acceptance](gemini-live-verification.md): model access works, but
generation service/quota failures prevented complete reviews; production AI
screening is not yet accepted.

[Reliability diagnosis](gemini-reliability.md) confirms a live 20-request daily
quota rejection and documents persistent provider backoff, AI Studio quota checks
and the deliberately stopped single-attempt diagnostic.

| Document | Purpose |
| --- | --- |
| [product-requirements.md](product-requirements.md) | Goals, boundaries, priorities, and success metrics |
| [architecture.md](architecture.md) | Component boundaries and end-to-end data flow |
| [roadmap.md](roadmap.md) | Development milestones with acceptance criteria |
| [phase-2-greenhouse-design.md](phase-2-greenhouse-design.md) | Approved Greenhouse collector specification, implementation details, and limits |
| [data-model.md](data-model.md) | Initial persistent entities and identity rules |
| [source-monitoring.md](source-monitoring.md) | ATS adapters, discovery, polling, and freshness semantics |
| [ai-screening.md](ai-screening.md) | Candidate policies, evidence, AI workflow, and outputs |
| [operations-security.md](operations-security.md) | Scheduling, observability, reliability, cost and privacy |
| [testing.md](testing.md) | Test pyramid, regression cases and quality gates |
| [adr/](adr/) | Architecture Decision Records; review status before building |

**Rule:** Update an ADR when a major architectural decision changes. Update the appropriate design document when a smaller implementation detail changes. Avoid duplicating volatile facts across files.

**Planned development order:** Registry/storage → one public ATS collector → change detection → additional ATS adapters → AI screening → alerts → employer discovery → daily reporting/deployment. See [roadmap.md](roadmap.md) for the authoritative milestones.

**External references:**
- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Ashby Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [Lever Postings API](https://github.com/lever/postings-api)
- [uv Project Guide](https://docs.astral.sh/uv/guides/projects/)

## Approved foundation decisions (2026-10-27)

- [ADR 0001: Modular monolith](adr/0001-modular-monolith.md) — Accepted
- [ADR 0004: SQLite first](adr/0004-sqlite-first.md) — Accepted
- [ADR 0005: Greenhouse first](adr/0005-greenhouse-first.md) — Accepted
- [ADR 0006: SQLAlchemy 2.x + Alembic](adr/0006-sqlalchemy-alembic.md) — Accepted
- [Phase 1 registry implementation](../src/jobsfinder_io/registry.py) — Approved fields, persistence, and argparse CLI implemented; the earlier Phase 1 design file is absent from this checkout
- [Phase 2 Greenhouse specification](phase-2-greenhouse-design.md) — Manual read-only collection and safe state comparison implemented
- [ADR 0007: Docker and CI](adr/0007-docker-and-ci.md) — Approved Phase 3 scope and local container/CI operation

ADRs 0002 and 0003 are accepted by the owner. Greenhouse polling is implemented in Phase 2; AI screening remains deferred.

**Phase 1 schema scope:** exactly four tables initially: `employers`, `job_sources`, `postings`, `poll_runs`. Other entities in `data-model.md` are explicitly deferred. Database access uses SQLAlchemy 2.x, and schema evolution uses Alembic from the first migration (ADR 0006).
