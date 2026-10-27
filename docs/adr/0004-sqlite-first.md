# ADR 0004 — Use SQLite for initial local persistence

- **Status:** Accepted — approved by project owner
- **Date:** 2026-10-27

## Context

The first implementation milestone needs a persistent registry, job identity, and poll history while the app runs locally as one Python process. There is no demonstrated need for network database access, multiple writer processes, or operational infrastructure at this point.

## Options

1. **SQLite initially, with an explicit migration path to PostgreSQL**: zero external service, straightforward local testing, supports transactions and unique constraints.
2. PostgreSQL immediately: stronger concurrency and production parity, but needs database installation/configuration for the initial feature.
3. Flat JSON files: simple start, but weak relational consistency and concurrent transaction safety.

## Decision

Use SQLite in Phase 1. Keep DB access behind small repository/service interfaces and avoid SQLite-specific business logic where practicable. **SQLAlchemy 2.x and Alembic are now separately accepted in ADR 0006 (2026-10-27).** This ADR governs the database engine choice; ADR 0006 governs ORM and schema migrations.

## Consequences and revisit triggers

- Use a single writer or correctly serialized writes for local polling; set SQLite busy timeout and make writes transactional.
- Persist timestamps in an explicit UTC convention rather than relying on SQLite native timezone semantics.
- Keep application data in ignored local storage, not in Git.
- Revisit PostgreSQL for durable hosted operation, multiple concurrent collectors, high write contention, or operational requirements. Migration needs testing; it is not automatic merely because an ORM is used.
