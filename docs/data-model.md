# Persistent Data Model (Proposed v0.1)

All times stored in UTC (timezone-aware); convert to `America/New_York` for reports. This is a conceptual model, not a committed SQL schema.

## Core entities

### `employers`

`id`, `name`, `official_domain`, `country/region` (where known), `industry` (optional), `created_at`, `updated_at`. Employer identity may need manual reconciliation; same employer can operate multiple ATS sources.

### `job_sources`

`id`, `employer_id`, `provider` (greenhouse/lever/ashby/custom), `public_board_identifier`, `canonical_careers_url`, `validated_endpoint`, `validation_evidence`, `monitoring_status`, `poll_interval_minutes`, `last_success_at`, `last_attempt_at`, `failure_count`, `created_at`.

**Unique candidate key:** `(provider, public_board_identifier, employer_id)`; revisit if the same actual board has multiple employer aliases. Never treat all Greenhouse companies as one API endpoint.

### `poll_runs`

`id`, `source_id`, `started_at`, `completed_at`, `status` (`complete_success`, `partial`, `failed`, `not_modified` if reliably supported), `http_status`, `pages_expected`, `pages_retrieved`, `post_count`, `error_code`, `error_message` (sanitized). A poll must be proven complete before absence becomes negative evidence.

### `postings`

`id`, `source_id`, `external_posting_id`, `external_requisition_id` (nullable), `canonical_job_url`, `apply_url`, `title`, `description_text`, `location_json`, `employment_type`, `remote_type`, `country`, `source_published_at` (nullable), `source_updated_at` (nullable), `date_provenance`, `first_seen_at`, `last_seen_at`, `last_changed_at`, `content_hash`, `status` (`active`, `missing_pending`, `closed`, `unknown`), `discovery_type` (`baseline`, `incremental`, `discovery_backfill`).

**Unique key:** `(source_id, external_posting_id)`; two different requisitions must never collapse merely because company/title/location match. Multi-location metadata is retained for one source post. Cross-source matching is an independent cautious review step.

### `posting_observations` (initially optional)

`id`, `posting_id`, `poll_run_id`, `observed_at`, `content_hash`, `raw_payload_ref`/small sanitized JSON, `change_kind`, `evidence`. To keep costs low, store changed snapshots and lightweight observations rather than duplicating every unchanged full description hourly.

### `screening_results`

`id`, `posting_id`, `profile_key` (`us`/`international`), `created_at`, `policy_version`, `prompt_version`, `model`, `classification`, `visa_class`, `start_class`, `experience_note`, `evidence_json`, `uncertainty_json`, `human_override`, `source_content_hash`. Screen only on new or materially changed description/policy unless recheck is scheduled.

### `deliveries`

`id`, `posting_id`, `profile_key`, `delivery_type`, `idempotency_key`, `created_at`, `delivered_at`, `status`, `retry_count`. Keep alerts deduplicated across restarts.

### `discovery_candidates` (later phase)

`id`, `employer_name`, `source_url`, `discovery_method`, `discovered_at`, `validation_status`, `validation_note`, `promoted_source_id`.

### `application_tracking` (optional, private)

Track `posting_id`, manually entered `applied_at`, status, deadlines and notes. No inferred applications. This table and associated data are personal; do not publish or expose in fixtures.

## Identity, dates, and state transitions

- **`first_seen_at`**: first time *our collector* successfully observed this ID; always available if collected.
- **`source_published_at`**: supplied by a trusted source; nullable. A provider's `publishedAt` may mean most recent publication/republication.
- **`source_updated_at`**: source-reported modification; not proof of original publication.
- **`last_seen_at`**: last complete/credible source observation.
- **`last_changed_at`**: when collector observed a substantive data change.
- **Freshness classes**: `verified_recent`, `source_last_published_recent`, `first_seen_recent_only`, `unknown`, `older`; don't promote an update/crawl timestamp to original publication.
- Baseline scan captures existing posts as **baseline**, not `newly_posted`.
- Missing from a successful complete poll means `missing_pending`; repeated complete misses or explicit closure evidence may justify `closed` only under documented policy.
- Reappearing ID: preserve identity and history, flag as `reappeared` or verified repost, not a wholly unrelated job.

## Integrity constraints

- Inserts/upserts must be idempotent; processing the same poll twice must not duplicate jobs or notifications.
- Transactions should cover poll-success bookkeeping and corresponding complete-source comparison, or use safe recoverable markers.
- Preserve provenance and prior screening history; later human overrides must not disappear on re-screen.
- Never store secrets in job payloads, error messages, or audit logs.

## To decide before Phase 1

- SQLite first vs. PostgreSQL immediately; which ORM/migration tool to introduce and when.
- Whether raw provider payloads are kept in DB or compact local object files.
- Closure policy (`2` complete misses is a candidate, **not** an accepted rule).
- How to represent an employer with multiple regional boards or mirrored ATS sites.
