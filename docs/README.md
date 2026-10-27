# JobsFinder.io — Documentation Index

**Project state:** Planning v0.1, October 2026. Architectural decisions are **proposed** until explicitly accepted by the project owner. No implementation is claimed by these documents.

| Document | Purpose |
| --- | --- |
| [product-requirements.md](product-requirements.md) | Goals, boundaries, priorities, and success metrics |
| [architecture.md](architecture.md) | Component boundaries and end-to-end data flow |
| [roadmap.md](roadmap.md) | Development milestones with acceptance criteria |
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
