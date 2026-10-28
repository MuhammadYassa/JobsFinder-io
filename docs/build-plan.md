# Integrated build progress

Owner authorization: complete remaining system, 2026-10-27. Preserve the
modular monolith, existing registry/polling semantics, uv and argparse.

## Shared contracts and ownership

- Lead: ORM models/migration, CLI integration, ingestion reconciliation, dependencies,
  end-to-end integration and final documentation.
- ATS agent: `sources/` adapters, `registry.py`, ATS tests only. Reuse normalized
  `GreenhouseJob` contract; add `locations: str = ""`. Expose
  `sources.adapters.make_collector(provider, client)` and `source_endpoint`.
- Screening agent: `screening/` and its tests only. Entry point
  `screen_jobs(engine, profile_path, *, api_key=None, preliminary_model=...,
  review_model=..., max_calls=20, client=None) -> dict`. Load private JSON profile;
  persist ScreeningResult; no private facts in tracked examples.
- Discovery agent: `discovery/` and tests only. Entry point
  `discover(engine, candidates_path, *, client=None) -> dict`; JSON candidate
  records with name, careers_url; verify official association before activation.
- Reporting agent (next wave): `reporting/` and tests. Entry point
  `generate_reports(engine, output_dir, *, profile_path=None, now=None) -> dict`.
- Scheduling agent (next wave): `operations/`, deployment files and tests.
- QA agent (final wave): independent review and regression tests.

Lead-owned persistent additions: Posting.locations (text), last_changed_at (UTC),
discovery_kind (baseline/new), revision (integer incremented on edits/reappearance).
ScreeningResult: id, posting_id, content_hash, profile_hash, policy_version,
prompt_version, model, stage, pipeline (us/international), disposition
(recommend/stretch/needs_review/reject), score, payload (JSON), created_at.
Delivery: id, posting_id, revision, pipeline, channel, status, artifact_path,
created_at, sent_at; unique posting/revision/pipeline/channel.
DiscoveryAttempt: id, candidate_url, method, status, payload JSON, created_at.
TaskRun: id, task_key unique, status, started_at, completed_at, payload JSON.
All imports from persistence.models; services own short transactions. No network
inside a database transaction. UTC storage, ZoneInfo scheduling. No live API calls
in tests. No deployment, actual notifications or paid calls during development.

## Progress

- [x] Inspect foundation and ADRs; identify extension boundaries.
- [x] ATS adapters, discovery and structured screening.
- [x] Durable schema extensions and reconciliation integration.
- [x] Reporting, letters, optional Telegram and scheduling.
- [x] CLI, deployment instructions, CI and migration compatibility.
- [x] Independent QA, offline end-to-end dry run, tests and Ruff.

## Validation log

- Baseline: 105 tests passed before implementation.
- Final acceptance: `uv run pytest -q`: 225 passed.
- Ruff lint and format checks passed (63 Python files); `git diff --check` passed.
- `docker compose config --quiet` and final `docker compose build`: passed.
- Actual non-root containers: initial/repeated Alembic upgrade, `alembic check`,
  registry write retained across rebuilt image/separate containers, `health`,
  two `run-due` ticks passed. Second tick reports `already_complete`.
- Container checks used ignored `data/docker-smoke`, a synthetic employer and
  zero sources/credentials. No employer, OpenAI, Brave or Telegram calls occurred.
- Full mocked dry run: two employers, two sources, three final active postings,
  seven delivery receipts; cache, reports/letters, alerts, failures, closure and
  reappearance exercised. See tests/test_end_to_end.py.
- Independent reviewers found and corrected location attribution, stale-profile
  alert filtering, report routing, negated exclusion evidence, unrelated start
  dates and uncertain-delivery CLI exit status.

Live credentials/model quality and hosting remain unverified. Discovery coverage
depends on configured candidates/providers; unknown search domains require
confirmation. No production schedule, deployment, paid API calls, commits or
pushes were performed.

Private handoff: an ignored local profile was prepared from the owner's supplied
facts at `data/private/profile.json`; no identifying profile facts enter tracked
configuration. Review it and supply official candidate career URLs before use.

## Gemini provider migration — 2026-10-27

- [x] Inspect screening, cache, local letter generation, usage budgets and configuration.
- [x] Use official `google-genai` SDK (locked 2.33.0), default `gemini-3.8-flash`.
- [x] Retain eligibility/evidence rules, schema, two stages, budgets and safe fallbacks.
- [x] Disable hidden SDK retries/continuations; count each bounded application retry.
- [x] Rename active settings to GEMINI_API_KEY / GEMINI_* model and cap options.
- [x] Preserve ignored local zero request cap and external database mount.
- [x] Invalidate old cache with eligibility-v3-gemini while retaining history/schema.
- [x] Convert HTTP mocks to actual Gemini wire responses via the real SDK.
- [x] Full suite: 240 passed; includes cache, model overrides, missing key, budgeted
  retries, blocked/truncated outputs, timeout/auth/model errors, and full pipeline.
- [x] Ruff lint/format passed (65 files); Docker build, Compose validation and
  container SDK import/model-default smoke checks passed without API requests.

No OpenAI SDK dependency existed; httpx is still used by other integrations.
Local cover letters are unchanged and require no provider. Live Gemini account
access, schema compatibility/output limits, decision quality and actual usage
remain unverified; no paid requests, production scheduling or deployment occurred.
See ADR 0009 for provider data-handling differences and configuration.

## Controlled live Gemini verification — 2026-10-27

- Read-only model metadata succeeded; key presence checked without disclosure.
- Only IDs 34, 40, 56, 67, 68, 69, 77, 82 were attempted. No other job was screened.
- Persisted ceiling of 40 generation attempts enforced; global zero cap preserved.
- Three JSON responses; 35 HTTP errors (11x504, 8x503, 16x429); two initial local
  verification-helper client failures retained in audit. One model-metadata GET.
- 6,886 reported tokens; returned-response paid list estimate $0.0074055,
  excluding unknown failed-request usage/account billing differences.
- All 16 final policy results remain reviewable. Two correct grounded senior
  preliminary rejections; an ungrounded backend recommendation was blocked.
- No final review completed, so live successful-result cache hits remain unverified.
- Fixed selected-job isolation/CLI, evidence schema, bounded latency configuration,
  flexible-start false rejection, invalid-output usage retention and unattempted
  preliminary history writes on an exhausted budget. Cache version now v4.
- Final budget replay: zero calls, zero new result rows. All 104 postings remain
  active; deliveries zero. No scheduling, deployment, commits or pushes.

See docs/gemini-live-verification.md for coverage gaps, counts and retest criteria.
Production AI acceptance remains blocked by provider service/quota failures.

Post-fix validation: 254 tests passed; Ruff lint/format and diff checks passed.

## Gemini reliability follow-up — 2026-10-27

- [x] Confirm SDK retries were disabled; identify the per-job one-second retry storm.
- [x] Classify structured quota/rate hints without retaining raw error messages.
- [x] Persist provider backoff and Pacific-day reset in existing TaskRun records.
- [x] Keep failed jobs deferred/reviewable; expose no-retry CLI and health state.
- [x] Test retries, quota storms, backoff expiry, DST, privacy and pending replay.
- [x] One live single-attempt request: HTTP 429, explicit 20/day quota, reset
  2026-10-28T07:00:00Z. Structured request/expansion correctly skipped while blocked.
- [x] Global cap zero preserved; one new request reservation; no returned token
  metadata/cost, alerts, schedules, deployment, commits or pushes.

See docs/gemini-reliability.md for confirmed causes, quota-console instructions,
alternative-model evaluation and remaining live acceptance blockers.

Final reliability checks: 280 tests passed; Ruff lint/format and diff checks
passed. Real CLI health reports the persisted daily-quota backoff without secrets.
Local Docker build and the container's no-retry help smoke check also passed.

## Non-AI production completion — implemented; activation pending

User authorizes SMTP to their configured personal recipient only; at most one
live test email during verification. No Gemini work/calls, paid search activation,
remote deployment or schedule installation. Preserve external Local AppData DB.

Shared contracts/file ownership before parallel implementation:

- SMTP agent owns `delivery/` and `tests/test_email.py`: SMTPConfig/load_smtp_config,
  enqueue_email(engine, key, subject, body, *, items=(), artifact_path=None),
  deliver_pending(engine, config, *, now=None, limit=10)->dict,
  send_test_email(engine, config)->dict. Use existing TaskRun for grouped outbox
  state and Delivery for per-posting receipts; no schema edits. Items are dicts
  {posting_id,revision,pipeline,channel}. Return safe states/counts; ambiguity is
  never automatically resent. SMTP explicit TLS/STARTTLS, bounded attempts.
- Reporting agent owns `reporting/non_ai.py`, `relevance.py`, and dedicated tests:
  generate_reports(engine,output_dir,*,now=None,slot_key=None,enqueue=True)->dict;
  notify_jobs(engine,output_dir,*,now=None,enqueue=True)->dict. No AI imports/calls
  or letters. Rolling seven-day results, grouped US/international message,
  baselines separated, conservative deterministic relevance and evidence; use
  delivery.enqueue_email with item receipts and stable slot/event keys.
- Discovery agent owns `discovery/`, discovery tests and discovery docs:
  preserve discover() contract, add optional now for deterministic daily rotation,
  trusted-page imports, public directory-source ingestion requiring configured
  employer-domain confirmation, breadth query rotation, durable cursor/history,
  and measurable registry growth. Keep safety/robots checks; no live paid search.
- Lead owns operations scheduling (6 AM discovery, 10 AM/8 PM reports), CLI,
  Compose/env/deployment docs, shared schema only if essential, integration and
  live verification. Later independent QA uses available agents.

TaskRun email outbox key begins `email:`; states pending/sending/sent/failed/
uncertain. JSON payload contains message content/local artifact, items, bounded
attempt count, next_attempt_at, safe error. Delivery channel smtp_alert/smtp_report
reserved atomically at enqueue; mark sent only on acknowledged SMTP acceptance.
Failed pre-DATA attempts can retry; post-DATA ambiguity requires review. No
network inside DB transactions. All CLI workflow callers hold database_run_lock.

- [x] SMTP and grouped non-AI reports/alerts, persistent outbox and uncertainty.
- [x] Discovery breadth/rotation/provenance and 6 AM scheduling.
- [x] Zero-AI orchestration and cron/SMTP configuration; default request cap zero.
- [x] Independent QA, automated non-AI checks and Docker migration/CLI smoke tests.
- [x] Live polls, discovery growth 3→5 employers, 278 jobs, repeated-run dedup.
- [x] Local report generation; live email explicitly skipped: SMTP settings absent.

Verified details and limitations: [non-AI handoff](non-ai-verification.md).
Activation still needs SMTP credentials/personal recipient, successful one-email
inbox check, maintained discovery inputs, and an always-on host's schedule.
Nothing deployed, scheduled, committed or pushed. Gemini untouched and uncalled.

Final validation: 236 non-AI tests passed (7 AI-specific cases deselected and
3 AI test modules excluded), Ruff lint/format passed, Docker build/Compose passed.
Network-disabled containers migrated an isolated database, passed Alembic check,
generated a local report, and skipped it after container restart. Real source
health is clean: 5 validated sources, 278 active baseline postings, 13 successful
poll records, no duplicate posting identities and no pending email outbox.

## Gemini multi-job screening — implemented, live activation disabled

Approved scope: persistent per-revision queue, multi-job structured requests,
independent per-policy validated results/cache, bounded token-aware packing,
Pacific-day/RPM/TPM request reservations and provider backoff. Reuse TaskRun and
ScreeningResult; no migration. Existing individual request helpers remain for
compatibility/regression coverage, but operational `screen` uses batching.
Separate `screen-due` sessions at 09:30/19:30 New York use their own process lock
so slow Gemini requests cannot block hourly monitoring. Default activation false
and max calls zero; no live requests, deployment or host schedule changes.

- [x] Batch queue, packing, structured validation, cache and request accounting.
- [x] Screen CLI and opt-in sessions; non-AI queue maintenance.
- [x] Mocked failure/partial/quota/restart/DST tests and full regression suite.
- [x] Ruff, Docker, documentation and controlled-live-test instructions.

Final checks: **372 tests passed**, Ruff lint/format passed, Docker build and
Compose validation passed. Network-disabled container migration, Alembic schema
check, screen help and disabled screen-due passed. Production disabled screen-due
persisted **252 pending candidates**; historical screening rows stayed 75 and
the old request count stayed 41. No new API request reservations or paid calls.
Source polling, discovery, delivery and report behavior were retained. No schema
migration, remote deployment, actual host scheduling, commit or push.

See [batch guide](gemini-batch-screening.md) for default 10-job sizing, optional
25-job settings, request estimates, independent session cron and later controlled
live acceptance. Serialization tests do not establish model accuracy or capacity.
