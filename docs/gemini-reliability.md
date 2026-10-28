# Gemini reliability diagnosis — 2026-10-27

Current batch update: [ADR 0010](adr/0010-multi-job-gemini-screening.md) replaces
operational per-job requests with batches and moves the enforced daily cap to
Pacific midnight. The UTC counters described below are historical audit records.
Provider-error classification/backoff and the live quota diagnosis remain valid.

## Confirmed findings

- The earlier audit contained 11 HTTP 504 server deadline failures, eight HTTP
  503 availability/overload responses, 16 HTTP 429 responses and two local
  AttributeErrors from the temporary verification helper's import collision.
  The old audit omitted provider error bodies, quota metrics and retry hints, so
  its 429s cannot retrospectively be divided into daily exhaustion and rate limits.
- A new **single-attempt** simple generation request returned HTTP 429 with an
  explicit **20 requests/day** quota and retry instruction. Daily quota exhaustion
  for the configured model/project is now confirmed. This is an observed project
  limit, not a universal Gemini limit.
- Its retry instruction and Pacific-day reset defer requests until
  **2026-10-28 07:00 UTC (03:00 America/New_York)**. The structured diagnostic was
  deliberately not sent against an exhausted daily quota. No expansion occurred.
- This diagnosis used **one new generation attempt**, no automatic retries, and
  no returned token metadata. Token usage/cost for the denied request is unknown;
  no successful generated tokens were received. The independent application
  reservation counter went from 40 to 41; the global configured cap remains zero.
- SDK default is five total attempts when not configured. JobsFinder explicitly
  used one SDK attempt at both client and request level, disabled continuation and
  tool calling, and added at most one application retry. There was no nested SDK
  retry multiplication. The real defects were one-second quota retries and no
  shared backoff across jobs, policies and later invocations.
- Verified settings: `gemini-3.8-flash`, low thinking for Gemini 3.x, 4,096 output
  tokens, JSON MIME/schema, bounded 90-second screening timeout. Earlier completed
  outputs took 65–72 seconds, so raising the earlier 45-second limit was justified,
  but longer deadlines cannot repair an exhausted quota or server overload.

## Changes

`screening/reliability.py` distinguishes daily quota, account/spend quota, known
rate limits, ambiguous 429, overload, server deadline, client timeout, network,
authentication/model errors and local client errors. It interprets quota
violations, RetryInfo duration and numeric/HTTP-date Retry-After. Only fixed error
categories, numeric status/delay and timestamps are saved/logged; raw error bodies,
messages, request headers, project identifiers and credentials are not retained.

- No immediate retry for any 429. Known daily/account quotas defer to the next
  Pacific midnight, or longer when requested by the provider. Account/prepay
  problems also require owner resolution; a date reset does not repair billing.
- Known rate limits defer at least one minute; ambiguous 429s start at 15 minutes
  and back off to six hours. Provider instructions always take precedence when
  they require a longer delay.
- 500/502/503 may receive one bounded application retry with exponential delay
  and jitter. Long provider delays defer instead of blocking the command. Once
  exhausted, a persistent 5–60-minute backoff stops subsequent calls. Slow server
  deadlines and client/network timeouts defer without immediate repeat calls.
- Backoff survives restart in existing TaskRun JSON records; no migration was
  needed. A credential digest and canonical model identify the local state. Google
  quotas remain project-wide: rotating keys is not a supported workaround.
- `screen --no-retries` permits one application attempt; the SDK still gets one
  attempt. `health` exposes active provider backoffs without credentials/digests.
- Failures stay `needs_review` with `deferred=true`, reason and retry time. They
  are never cached as successful eligibility decisions, rejected or discarded.
  Expired backoff permits normal retry; successful responses clear failure state.

## Check the actual project quota

1. Sign in to [AI Studio API keys](https://aistudio.google.com/api-keys) and identify
   the project belonging to the configured key. Do not post or print the key.
2. Open [AI Studio rate limits](https://aistudio.google.com/rate-limit), select
   that same project and `gemini-3.8-flash`. Inspect RPM, input TPM, RPD, current
   usage/tier and the relevant time range. Other applications and keys in that
   project share its limits.
3. Check the project's usage/billing pages for spend caps, prepaid balance and
   billing restrictions. Resolve these only through the owner's account; this
   task did not enable billing, purchase credits or change cloud quotas.
4. Daily provider limits reset at midnight Pacific, including DST. JobsFinder's
   independent reservation budget resets at UTC midnight. Increasing
   `GEMINI_MAX_CALLS` cannot raise Google's limits. Keep the global cap at zero
   until controlled diagnostics and complete screening reviews pass.

These pages require the owner's Google login/permissions; no authenticated
dashboard was accessible during this task. The observed 20/day limit came from
the actual API rejection, not from guessing a tier.

## Optional alternative

Google documents `gemini-3.6-flash` as an available previous-generation model with
structured outputs. It can be selected explicitly using
`GEMINI_PRELIMINARY_MODEL` / `GEMINI_REVIEW_MODEL`, or CLI model options. No
automatic model switching was added. It may help model-specific capacity or
latency problems; shared project/billing limits may still apply. Check that
model's actual quota first and validate its screening quality with a small batch.
Gemini 3.5 Flash is deprecated/redirected, so do not choose it as a stable fallback.
No alternative-model live calls were made, and the default remains 3.8 Flash.

## Retest and learning checkpoint

Validation: **280 automated tests passed**, including quota/rate separation,
RetryInfo/HTTP-date handling, Pacific DST resets, no nested SDK retries, pending
reprocessing, backoff expiry, no-retry CLI and sanitized health visibility.
Ruff lint/format checks passed. These checks use mocked APIs and add no live usage.
The local Docker image rebuilt successfully; its CLI exposes `--no-retries`.

After the provider block expires and the console confirms remaining quota, repeat
one simple and one structured request with retries disabled. Expand to a small
selected batch only after both pass. Production screening remains unaccepted:
the structured diagnostic, completed-review caching and broader classification
quality could not be live-verified while daily quota was exhausted.

Trace `classify_error()` → `defer_provider()` → `provider_block()` in the new
module, then `_request()`'s check **before** `_reserve_call()`. A provider cooldown
must stop later jobs without consuming request reservations or changing eligibility.

References:

- [Google rate limits and Pacific reset](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Google troubleshooting and retry guidance](https://ai.google.dev/gemini-api/docs/troubleshooting)
- [Google GenAI SDK](https://googleapis.github.io/python-genai/)
- [Gemini 3.6 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash)
