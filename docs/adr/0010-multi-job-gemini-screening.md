# ADR 0010 — Multi-job Gemini screening

- Status: Accepted by the owner's batch-screening implementation request
- Date: 2026-10-27
- Supersedes: ADR 0009's operational per-job/two-stage request flow and UTC cap

Use synchronous `generate_content` requests containing several complete job
descriptions. This is prompt batching, not Google's asynchronous Batch API or a
claim of discounted pricing. Default model remains `gemini-3.8-flash`.

One full review evaluates each job against its requested US/international
policies, using the existing private-profile loader and independent evidence
validator. The former preliminary/review per-job helper remains for compatibility
and regression coverage; operational `screen_jobs` and CLI `screen` use batches.
`--review-model` remains compatible; `--model`/`GEMINI_BATCH_MODEL` are preferred.

Default packing is at most 10 jobs, 24,000 estimated input tokens, and 24,576
output tokens with 1,600 expected output tokens per job plus thinking/headroom.
Packing supports up to 25 jobs with suitable configured input/output budgets.
Descriptions are never silently truncated. Counts, IDs, per-policy schemas and
exact evidence/source URLs are validated independently of the model schema.
Valid results survive partial responses; invalid/omitted jobs remain pending.
Repeated/truncated oversized outputs reduce the next batch size.

Reuse TaskRun for per-revision queue receipts, session state, token-count cache,
request records and quota reservations. ScreeningResult stores each successful
job/policy separately with its content/profile/policy/model/prompt identity and
the shared batch request key. Request usage is stored once on the request record,
not duplicated across results. Successful compatible pre-batch reviews can be
reused. No schema migration is required.

`run-due` only maintains the queue; it never calls AI. Separate `screen-due`
five-minute ticks process sessions during 09:30–10:00 and 19:30–20:00 New York.
A separate screening process lock prevents overlapping screeners while allowing
monitoring to continue during API waits. All shared SQLite writes acquire short
writer transactions; network calls hold no database transaction. Sessions resume
pending work and become complete only when current work is cached/successful.

Reserve all calls, including failures and optional token counting, atomically.
The 20-call application ceiling follows Pacific midnight/DST; two calls are
reserved for previously attempted jobs. The older UTC counters remain audit
history, not the resetting quota limit. RPM/input-TPM reservations and provider
backoff persist across commands/restarts. SDK retries/continuation are disabled.
Provider errors defer work; no immediate retries. Each job has at most two
generation attempts per Pacific day by default. External consumers of the same
Google project remain outside local accounting; actual provider errors win.

Both `GEMINI_BATCH_ENABLED=false` and `GEMINI_MAX_CALLS=0` remain defaults. A
manual `screen --max-calls N` is a separately explicit controlled invocation;
it does not enable scheduled screening. No live calls or host schedules were
performed during implementation. Larger-batch accuracy and service capacity
still require a controlled live test.

References:

- [Structured JSON output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Token counting](https://ai.google.dev/gemini-api/docs/tokens)
- [Project rate limits and Pacific reset](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini 3.8 Flash model limits](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
