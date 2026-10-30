# Architecture Decision Records (ADRs)

Each ADR records the problem, options, proposed/accepted choice, tradeoffs, and consequences. **Status: Proposed** means the project owner has **not yet approved** implementation on that basis.

- [0009 — Gemini screening](0009-gemini-screening.md) — Accepted provider migration; supersedes OpenAI portions of ADR 0008.

- [0008 — Integrated personal workflow](0008-integrated-personal-workflow.md) — Accepted by complete-system implementation request; supersedes earlier deferred scope.

- [0001 — Modular monolith for MVP](0001-modular-monolith.md)
- [0002 — Public-source polling and provenance](0002-poll-and-provenance.md)
- [0003 — Deterministic pipeline with bounded AI](0003-ai-gated-screening.md)
- [0004 — SQLite first](0004-sqlite-first.md)
- [0005 — Greenhouse first](0005-greenhouse-first.md)
- [0006 — SQLAlchemy 2.x + Alembic](0006-sqlalchemy-alembic.md)
- [0007 — Local Docker packaging and GitHub Actions CI](0007-docker-and-ci.md)

When approved, change an ADR's status to **Accepted** and record the date. A new decision superseding an accepted ADR should reference the prior one rather than silently rewriting history.

## Decision status update (2026-10-27)

- [0012 — Pull-based production deployment](0012-pull-based-production-deployment.md)
  — Accepted by the owner's Azure CI/CD request; supersedes CI-only publishing.

- 0001 — Accepted
- 0002 — Accepted (implementation remains phased)
- 0003 — Accepted (implementation deferred beyond Phase 1)
- 0004 — Accepted
- 0005 — Accepted
- 0006 — Accepted
- 0007 — Accepted (Phase 3 Docker/CI scope)
- [0010 — Multi-job Gemini screening](0010-multi-job-gemini-screening.md) — Accepted;
  implementation remains disabled pending controlled live acceptance.
- [0011 — Flash-Lite primary model](0011-flash-lite-screening.md) — Accepted;
  one selected live batch verified, scheduled activation still disabled.
