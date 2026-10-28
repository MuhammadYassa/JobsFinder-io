# AGENTS.md — JobsFinder.io

This is the primary instruction file for AI coding agents working on JobsFinder.io. Read this file, `docs/README.md`, `docs/roadmap.md`, and relevant architecture/ADR documents before modifying code.

## Purpose

Maintain the reliable, inexpensive **personal** Python system that discovers employers, monitors publicly accessible career feeds for new software-development jobs, screens them against configurable US and international eligibility rules, and sends actionable alerts/reports. The system **does not submit applications or contact employers**.

Success means earlier detection, accurate provenance, low false negatives, auditability, and a maintainable system—not sophisticated agent orchestration or a public SaaS product.

## Project status and decision authority

- Development is complete; the repository is being prepared for Azure deployment. Host provisioning and permanent schedules remain deployment steps. Historical documents tagged **Proposed** are design context, not implementation authorization.
- **Accepted foundations:** modular Python monolith, SQLite, SQLAlchemy 2.x, Alembic, Docker and CLI scheduling. ADR 0008 extends the original four-table schema with workflow tables; ADRs 0009–0011 record Gemini screening and approved capped activation. Preserve both migrations and all existing history.
- The human owner chooses architecture and approves maintenance scope. Explain meaningful tradeoffs before major decisions and implement only the requested change.
- Never silently add new external services, paid APIs, browser automation, authentication, dashboards, or autonomous agents.
- Keep documentation consistent with code. If a proposed choice changes, update the appropriate ADR with rationale and consequences after approval.

## Current repository and tooling

- Python >=3.12; dependencies in `pyproject.toml`/`uv.lock`, application in `src/jobsfinder_io/`.
- Prefer `uv run ...` and `uv add ...` to managing a separate requirements file.
- Before editing, inspect the current tree and `pyproject.toml`; never assume packages or commands already exist.
- pytest and Ruff are configured. For executable changes, run relevant tests and style checks: `uv run pytest`, `uv run ruff check .`, and `uv run ruff format --check .`. Scale checks to the requested scope; documentation-only cleanup does not need a full test cycle.
- Prefer type hints, small well-named functions, explicit return types at interfaces, and clear exceptions. Keep module interfaces simple and testable.

## Architecture boundaries (see ADRs)

- **Collectors** access official, public, permitted listings. They do not make AI calls and never submit applications.
- **Registry/discovery** store and validate employers, source identifiers, provenance, and monitoring status.
- **Normalization + persistence** turn provider-specific payloads into consistent records while preserving source-specific IDs and raw evidence when appropriate. Persistence uses SQLAlchemy 2.x ORM models, SQLite on persistent local disk, and Alembic for version-controlled migrations. Schema changes require a migration and an approved maintenance task.
- **Change detection** compares actual employer/source posting identities, not search-index timestamps, and records successes/failures.
- **Screening** performs conservative deterministic filtering, then evidence-grounded AI review on candidates. Unknown is a valid outcome.
- **Delivery** sends notifications and generates reports only after validated state transitions, with no duplicate alerts.
- Keep US and international eligibility policies separate but reuse the same collection/persistence core.

## Non-negotiable correctness rules

1. A job first seen now was **not necessarily posted now**. Track source publication (if trustworthy), source update, first-seen, and last-seen separately, with provenance and uncertainty.
2. A successful *first* source scan establishes a baseline. Existing posts are not newly published jobs; optionally queue them as clearly labeled baseline discoveries.
3. Do not close jobs because a source timed out, returned an error, or produced an incomplete response. Require explicit evidence or a documented missing-on-successful-scans policy.
4. Unique identity is at least `(source_id, source_posting_id)`. Cross-source deduplication must be conservative and auditable.
5. Avoid false negatives. Do not discard ambiguous engineering roles or treat visa/sponsorship silence as rejection.
6. Distinguish explicit eligibility requirements from preferences. Never infer sponsorship from company-level history or country visa rules alone.
7. Every AI finding must include a reason, evidence text/reference, model/prompt version, and an uncertainty or review state. No fabricated job facts.
8. All external API calls need reasonable rate limits, timeouts, bounded retries/backoff, and failure visibility. Respect provider terms and site policies. Do not evade access controls, CAPTCHAs, authentication, or anti-bot systems.
9. Never submit a job application, message a recruiter, or update an external account without explicit per-action authorization.
10. Never commit tokens, private profiles, immigration details, resumes, application histories, downloaded personal data, or proprietary pages to this public repository.

## AI-assisted development workflow

For each approved maintenance task:
1. Read relevant docs/code; briefly explain existing behavior and the targeted change.
2. State a small implementation plan and any unresolved decision or changed assumption.
3. For behavior changes, write or update tests, including failure paths and regression fixtures.
4. Implement the smallest coherent solution. Avoid overengineering, broad refactors, hidden network calls, and unnecessary dependencies.
5. Run checks appropriate to the change; state precisely which ran and which couldn't run. Do not run large verification cycles for documentation-only cleanup.
6. Provide a short handoff: changed files, important functions, rationale, tradeoffs, failure scenarios, and any unresolved issues.
7. Include a **learning checkpoint**: help the owner trace the key code and explain it independently.
8. Do not commit, push, merge, deploy, trigger paid services, or modify scheduled jobs unless specifically requested.

Preserve production databases, backups, employer registries, screening queues,
cached decisions, job history, private profiles, `.env`, credentials and user files.
Inspect cleanup targets and preserve uncertain files. Never run indiscriminate
Git cleanup/reset commands. Stop both worker schedules before migrations or
consistent offline backups; use SQLite's backup API for live database backups.

## Test expectations

- Collectors: use recorded/synthetic fixtures; avoid live network in unit tests.
- Change detection: first baseline, new post, changed description, disappeared post, reinstated post, failed/incomplete polls, and duplicate locations.
- Screening: flexible years/preferred vs required, unknown visa, explicit exclusions, time-to-graduation, and misleading titles.
- Persistence: idempotent upserts and safe reprocessing after crashes.
- Notifications: deduplication and retry idempotency.

## Documentation map

See `docs/README.md`. All architectural decisions belong in `docs/adr/`; roadmap acceptance criteria live in `docs/roadmap.md`. Keep design and implementation facts separate, and link official third-party API documentation when recording assumptions.
