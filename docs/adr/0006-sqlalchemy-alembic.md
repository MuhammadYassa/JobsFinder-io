# ADR 0006 — Use SQLAlchemy 2.x and Alembic from the first migration

- **Status:** Accepted — approved by project owner
- **Date:** 2026-10-27

## Context

JobsFinder.io starts with SQLite but expects multiple relational entities, repeatable schema changes, and a possible future PostgreSQL migration. Schema changes should be reproducible for clean checkouts and ongoing development.

## Options considered

1. **SQLAlchemy 2.x ORM + Alembic** — typed Python models, explicit transactional access, version-controlled schema migrations.
2. `sqlite3` + handwritten SQL/migrations — small dependency footprint but more manual schema and eventual database-transition work.
3. A different ORM/migration stack — feasible but brings no current advantage for this team's selected Python stack.

## Decision

- Use **SQLAlchemy 2.x**, with modern `DeclarativeBase` / `Mapped` / `mapped_column` style, for persistence models.
- Use **Alembic** for all database schema migrations, beginning with the first four-table schema.
- Use **SQLite** as the initial local database (ADR 0004), not PostgreSQL until a later decision.
- Initialize the initial database by running Alembic migrations; do not rely on `Base.metadata.create_all()` as the application's schema deployment mechanism.
- Start with **exactly four tables**: `employers`, `job_sources`, `postings`, `poll_runs`. Additional conceptual entities described elsewhere are deferred to later migrations.
- Keep transaction and repository/service boundaries simple. Add async DB access only if a proven requirement arises; synchronous ORM usage is sufficient for Phase 1.

## Consequences

- Need to configure `uv` dependencies and an Alembic environment, plus an initial migration revision.
- Maintain migration scripts in version control and test upgrades on clean temporary SQLite databases.
- Use UTC-normalized timestamps in application code; SQLite does not enforce timezone awareness in stored datetime values.
- Schema portability is improved, but a future PostgreSQL move will still require migration review and tests; it is not automatic.
- Avoid gratuitous ORM abstractions, complex generic repository frameworks, or premature session concurrency.
