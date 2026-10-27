# JobsFinder.io — Documentation Index

**Project state:** Phases 1–3 implemented. Local registry, four-table persistence, migrations, argparse CLI, manual Greenhouse collection, Docker Compose packaging, and CI configuration are available. Later features remain unimplemented. Decisions explicitly accepted by the owner are recorded as **Accepted**; others remain **Proposed**.

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
