# Testing and Quality Gates (Proposed v0.1)

## Principle

Tests must demonstrate both a **correct new-job alert** and **safe behavior during failures**. A collector that accidentally closes every job after a timeout is worse than one that misses a poll.

## Unit tests

- Provider normalization: missing fields, HTML descriptions, multiple locations, unlisted/open status, stable ID parsing.
- New source baseline vs incremental new ID, changed content, unchanged ID, and reappeared ID.
- Poll correctness: one bad page -> `partial`; 429, 500, timeout -> `failed` with bounded retry; absence not treated as closure.
- Date provenance: Greenhouse update must not be original publication; unknown stays unknown; timezone conversion.
- Screening eligibility: required/preferred experience, ambiguous roles, explicit no sponsorship, visa silence, future graduation, start-date unknown, misleading programming titles.
- Alert idempotency and repeated screening of identical content.

## Integration tests

- Temporary DB: Alembic `upgrade head` on a clean SQLite database creates the four approved domain tables; verify SQLAlchemy unique constraints, multi-source jobs, idempotent upsert, transaction rollback and crash/retry recovery. (Alembic adds its own `alembic_version` bookkeeping table.)
- Source collector with mocked HTTP pages: verify complete pagination, first baseline and subsequent change detection.
- End-to-end offline fixture: source -> normalization -> persistence -> screening stub -> alert stub.
- Optional slow opt-in live API smoke check only with source-policy compliance; live calls never required for normal unit tests.

## AI evaluation tests

- Build labeled fixtures from consented/public, compact excerpts with no identifying personal information.
- Check schema parsing and evidence fields, abstentions and failure behavior.
- Measure false negatives and uncertain classifications. Preserve examples when a false negative is fixed.
- Model/prompt version changes require re-evaluation of a stable test set and human review of regressions.

## Suggested tools (install as milestones require)

- `pytest` for unit/integration tests, `ruff` for lint/format, `httpx` mocking or local test server, SQLAlchemy 2.x for ORM access, Alembic for schema migrations, and lightweight temporary SQLite DB.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` **only once dependencies and configuration have been added**.

## Definition of done

- Happy path + important failure modes covered; no hidden live network, personal data or paid model calls in default tests.
- Agent lists tests run, results, unrun checks and rationale for technical decisions.
- User can trace and explain major functions after AI-assisted implementation.
