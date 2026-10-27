# Phase 1 — Employer Registry and Local Persistence (design draft)

**Status:** Proposed design for next owner review. No implementation yet.  
**Agreed foundations:** modular Python monolith (ADR 0001); SQLite first (ADR 0004); Greenhouse first adapter (ADR 0005); SQLAlchemy 2.x + Alembic migrations (ADR 0006); exactly four initial tables: `employers`, `job_sources`, `postings`, `poll_runs`. Field-level and CLI details below remain proposed until review.

## Goal and scope

Build a small persistent, testable foundation for storing companies and validated employer-specific job sources. Model the future collection data, but do not add network polling, AI screening, scheduled background jobs, alerts, or employer discovery in this phase.

## Four approved initial tables (proposed columns)

- **`employers`**: `id` (internal primary key), `name`, `official_domain` (nullable, normalized), `created_at`, `updated_at`. A company may have more than one public ATS source. Company identity needs explicit review when domains are absent/ambiguous.
- **`job_sources`**: `id`, `employer_id` (FK), `provider`, `board_identifier`, `careers_url`, `api_endpoint`, `status` (`candidate`, `validated`, `paused`, `error`), `validated_at` (nullable), `last_attempt_at`, `last_success_at`, `consecutive_failures`, `poll_interval_minutes`, `created_at`. Unique provider+board identifier (use provider-specific canonicalization). Do not equate a URL discovered by search with a validated employer source.
- **`postings`**: `id`, `source_id` (FK), `external_posting_id`, `external_requisition_id` (nullable), `title`, `canonical_job_url`, `apply_url`, `description_text`, `source_published_at` (nullable), `source_updated_at` (nullable), `date_provenance`, `first_seen_at`, `last_seen_at`, `content_hash`, `status` (`active`, `missing_pending`, `closed`, `unknown`). Unique `(source_id, external_posting_id)`; links, titles and locations are not reliable unique keys. Full posting capture begins in Phase 2.
- **`poll_runs`**: `id`, `source_id` (FK), `started_at`, `completed_at` (nullable), `status` (`running`, `complete_success`, `partial`, `failed`), `http_status`, `post_count`, `error_code`. Do not interpret job absence when a poll failed or was partial. Populated in Phase 2.

## Core relationships

`employers (1) → (many) job_sources → (many) postings`  
`job_sources (1) → (many) poll_runs`

## Proposed domain/service boundaries

- **Domain models**: entities, validation rules, provider-independent job identity.
- **Persistence/repository**: SQLAlchemy 2.x typed ORM models, session-managed SQLite transactions and simple CRUD; Alembic governs schema changes; no HTTP/LLM logic.
- **Registry service**: register an employer, register a source, list sources, and reject duplicates; verify provider association separately from CRUD.
- **CLI**: thin commands that call the registry service. Suggested initial actions: `add-employer`, `add-source`, `list-sources`; exact command names TBD.

## Data integrity rules

1. Persist times in UTC; presentation can later convert to America/New_York.
2. A public board token belongs to a provider + board; reject exact duplicates and avoid automatically merging ambiguous company names.
3. Preserve original posting identity across updates, removals and reappearances.
4. No claim that `first_seen_at` is original publication time. `source_updated_at` is not original publication time.
5. Initial complete scans later count as **baseline** observations, not proof that those jobs were posted today.
6. Mark a source validated only after checking association with an actual employer's official careers presence and public read-only access.
7. Store no personal profile, immigration details, API keys or application data in tracked fixtures or docs.
8. Tests must use temporary local databases so they cannot damage the user's registry.

## Phase 1 acceptance tests

- Create an employer and Greenhouse source; restart and read both back.
- A second insert of the same provider+board identifier does not produce a duplicate source.
- Two distinct ATS sources can belong to one employer.
- Unknown source/provider identifiers are rejected or clearly recorded as unsupported.
- Duplicate company-name ambiguity is not silently resolved by merging unrelated records.
- Local DB data and secrets are ignored by Git; `alembic upgrade head` creates exactly four tables (excluding Alembic's own version bookkeeping table), and setup works from a clean checkout.
- Test suite passes without internet or API keys; SQLAlchemy models/constraints and a clean Alembic migration are exercised in temporary databases.

## Open questions before implementation

- **Resolved:** SQLAlchemy 2.x + Alembic from the start (ADR 0006). Keep the implementation minimal; no custom generic ORM framework.
- CLI approach: `argparse` in the standard library vs. Typer. Recommendation: `argparse` for initial commands.
- Initial raw posting payload retention: store only normalized fields in SQLite for Phase 2, or also a compact provider JSON snapshot for auditability. Recommendation: preserve minimal source payload as needed for audit without accumulating unchanged full responses each hour.

## Out of scope

Actual Greenhouse HTTP calls, periodic monitoring, LLM classification, international visa research, employer discovery, deployment, notification delivery, and personalized cover letters are covered by later milestones.
