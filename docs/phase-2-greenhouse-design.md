# JobsFinder.io — Phase 2: Greenhouse Collector

**Status:** Approved for implementation by the owner; Phase 2 implemented.

**Depends on:** Completed Phase 1. Read `AGENTS.md` and the actual local SQLAlchemy models, migrations, registry service, and CLI before making changes. The previously referenced `docs/phase-1-registry-design.md` is absent from the current checkout. All four application tables are retained without a schema migration.

## Goal

Let us manually run one Greenhouse employer-board check from the terminal. Save its current public postings in SQLite. On later runs, detect which postings are new, changed, missing, or back. Record successful and failed checks. Do not use AI or run on a schedule yet.

## Source API

- List public posts: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- Individual public post details: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{id}`
- Public GET endpoints require no API key. Never submit applications.
- Official reference: https://docs.greenhouse.io/job-board.html

## Recommended flow

1. Load a registered Greenhouse `job_sources` record. Build/validate requests only against the expected Greenhouse host; do not fetch arbitrary addresses stored in the DB. Keep candidate vs. validated status honest: a successful HTTP request alone does not prove the board belongs to the intended employer.
2. Start a `poll_runs` row. Fetch the full public jobs list with a reasonable timeout and bounded retries. A timeout, malformed response, HTTP failure, or incomplete response must **not** be mistaken for an empty board.
3. For each listing, take the Greenhouse **post `id`** as `external_posting_id` (not `internal_job_id`). Use `requisition_id` for `external_requisition_id` when available; do not confuse these different IDs. Read title, location if the approved schema supports it, official URL, text description, and `updated_at`.
4. On first encounter (including the initial baseline), attempt the individual-job detail endpoint to retrieve `first_published` when exposed. Keep requests bounded and make enrichment failures visible; do not invent a publication date. Store any confirmed value as `source_published_at` with explicit `date_provenance`. If absent, leave publication date unknown. Never treat `updated_at` or `first_seen_at` as original publication.
5. Normalize readable description text, keep meaningful content hashes, and save changes transactionally. Preserve stable `(source_id, external_posting_id)` identity.
6. Compare against the **previous complete successful scan**. The first successful scan is a **baseline**: existing jobs are not automatically "posted today" or "new today". Subsequent complete scans classify new, unchanged, updated, missing, and reappearing posts.
7. On the first complete scan where an existing post disappears, set `missing_pending`; after a second consecutive complete scan without it, set `closed` (if Phase 1's persisted records support this reliably). If not, keep it `missing_pending` until the necessary design is approved. Failed/partial checks never advance missing/closure states. A reappearing post returns to `active` without creating a new posting row.
8. Finish the `poll_runs` record with status, count and error details; update source health timestamps/counters appropriately. Show a concise CLI summary.

## CLI, for manual testing only

Expose a command through the existing argparse CLI (names should match the current code style), such as:

`uv run jobsfinder-io poll-source --source-id 1`

Example output (illustrative): `complete_success | observed=25 | baseline=25 | new=0 | updated=0 | missing=0`.

Running this command is **not** an hourly schedule. Cron belongs to a later phase.

## Simple architecture

`CLI → Greenhouse HTTP collector → normalize/compare service → SQLAlchemy models → SQLite`

Keep HTTP-specific JSON parsing in the Greenhouse collector. Keep database writes and change detection separate. Avoid generic multi-ATS frameworks, background workers, LLM calls, extra application tables, or unrelated refactors.

## Required tests (no live network in automated tests)

- First complete scan establishes baseline and stores distinct post IDs.
- Repeating the same response creates no duplicates or false "new" jobs.
- Adding one post to a later response detects it once.
- Editing a description updates that post instead of inserting another.
- Missing post gets a cautious state, with no false closure after failed/partial scans.
- Reappearance reuses its original row and makes it active.
- A valid empty-board response is distinct from an HTTP failure or malformed/incomplete data.
- Greenhouse post ID, requisition ID and internal job ID remain distinct.
- `updated_at` does not populate `source_published_at`; `first_published` may be absent.
- `poll_runs` records success/failure accurately, and a subsequent successful retry recovers.
- At least one end-to-end test runs the CLI against an HTTP mock and a temporary SQLite database.
- Existing Phase 1 tests and Alembic migrations continue to pass.

## Boundaries and approval

- No AI screening, employer discovery, cron, notifications, applications, remote deployment, or Lever/Ashby integration.
- Reuse the approved four tables and existing fields. If a field or migration is truly necessary, explain the reason and get approval before expanding the schema.
- Preserve the user's local Phase 1 implementation. Do not overwrite unrelated files or push/commit without permission.
- After coding, give a short change summary, exact test commands/results, limitations, and a student-friendly walkthrough of the main data flow.

## Implementation notes

- `sources/greenhouse.py` owns public HTTP GET requests, JSON validation, readable
  description normalization, content hashes, and publication-date enrichment.
  `ingestion/polling.py` owns poll transactions and posting comparisons. The CLI
  calls the service without wrapping it in the Phase 1 single-command transaction.
- Polling requires a validated source, or an `error` source with a prior
  `validated_at`. Candidate/paused sources are refused and recorded without HTTP.
  Polling preserves source validation status; health timestamps and counters
  record success/failure independently. HTTP success never proves ownership.
- The endpoint is reconstructed from the validated board-token syntax. Stored
  endpoints and returned job links are never fetched. The client uses HTTPS to
  `boards-api.greenhouse.io`, disables redirects and environment proxy settings,
  and never requests application submissions.
- Each GET has a five-second connection timeout and 15-second read/write/pool
  timeouts. Responses are limited to 10 MiB of decoded data. Requests are spaced
  at least one second apart within a check. Transport errors, 429, and 5xx responses
  get at most three attempts with exponential backoff and jitter. `Retry-After`
  seconds/dates are honored up to 60 seconds; longer waits end the request without
  an early retry. A detail 429 stops remaining detail lookups for that check.
- The official API describes the board list as all posts. Completeness requires
  a jobs array, an integer `meta.total` matching its length, distinct positive post
  IDs, and valid required fields on every job. Missing totals, duplicate IDs, or
  malformed listings make the entire scan partial; no posting writes occur.
  Invalid JSON or HTTP/transport failures are failed polls. A valid empty board
  has `jobs=[]` and `meta.total=0`, and is a complete scan.
- HTML/entities and whitespace are normalized; scripts/styles are omitted.
  Hashes cover title, readable description, job URL, and requisition ID, excluding
  update timestamps. The API's `absolute_url` supplies both canonical and apply
  links; it is stored, not followed. Internal job IDs never become posting IDs.
- Up to 100 new or previously failed/deferred publication lookups run per check,
  each with the same request bounds. Details must match the requested post ID.
  Only a timezone-aware `first_published` becomes `source_published_at`, with
  `greenhouse.detail.first_published` provenance. Absent dates remain null with
  explicit provenance. Confirmed absence is not repeatedly fetched; errors and
  budget deferrals can be retried on later checks.
- Optional detail failures do not invalidate complete list coverage. The poll
  remains `complete_success` with a `publication_enrichment_failed:N` warning,
  per-post error provenance, and a CLI warning count. Existing publication
  evidence is preserved. List HTTP status is kept separate from detail status.
- The existence of a previous `complete_success` row establishes whether this is
  a baseline, including when the baseline was empty. Later new IDs are newly
  observed, not necessarily newly published. Existing IDs reuse their row and
  `first_seen_at`; `last_seen_at` advances only on complete successful scans.
- `missing_pending` records the first complete miss, and only another complete
  miss changes it to `closed`. Failed/partial scans neither advance nor reset
  this sequence. Reappearance changes the original row to `active` and resets
  the sequence. Reappearing jobs can also count as updated if content changed.
  Summary counts describe changes during that check, not cumulative status totals.
- A short writer transaction serializes running-poll checks and inserts before
  any HTTP requests. Posting writes, completion, and source success bookkeeping
  commit together. A persistence failure rolls back the whole snapshot and is
  recorded separately when SQLite remains writable. Repeated input is idempotent.
- Every check for an existing source gets a poll row, including refused checks.
  Each HTTP retry belongs to the same logical poll. Failed/partial polls increment
  `consecutive_failures`, leaving `last_success_at` unchanged. Complete lists reset
  the counter. Overlap refusals are recorded without incrementing failure count.
  Missing sources cannot have poll rows because the foreign key requires a source.

## Recovery and limits

Ordinary exceptions and keyboard interruptions attempt to finish the poll as
failed. A hard kill or unavailable database may leave a durable `running` row.
Further checks return `poll_in_progress` to avoid competing snapshots. Confirm
that no process is still checking that source, then manually mark that specific
orphaned poll failed (with a UTC completion time and `interrupted` error code)
before retrying. Automatic stale-run recovery and scheduling are deferred.

The four-table schema stores current normalized fields and date evidence. It has
no location column, raw JSON snapshot, per-post observation/change-history table,
or persisted per-post baseline flag. Location-only changes are therefore not
tracked; distinct post IDs remain separate even if titles/locations/internal IDs
match. The first complete poll and its count establish the baseline; the CLI's
detailed change counts describe the current run. No schema expansion was made.

Automated tests use synthetic fixtures, HTTPX mock transports, and Alembic-created
temporary databases. Real HTTP transport is blocked. Tests cover the required
scenarios plus retry limits, redirects, response limits, rate limiting, publication
evidence, independent boards, rollback after flushed writes, interruptions, and
the CLI-to-HTTP-to-SQLite path. No live employer-board smoke test was run.
