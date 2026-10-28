# ADR 0009 — Gemini screening through the Google GenAI SDK

Batch update: [ADR 0010](0010-multi-job-gemini-screening.md) supersedes operational
per-job requests and the UTC quota reset. The existing policy/evidence validator
remains in use. Batch sessions are opt-in and disabled by default.

- Status: Accepted by the owner's explicit provider migration request
- Date: 2026-10-27
- Supersedes: the OpenAI integration portion of ADR 0008

Reliability update: [diagnosis](../gemini-reliability.md) records shared persistent
provider backoff in existing TaskRun records, typed quota/rate/overload/deadline
failures, provider reset in Pacific time, and explicit no-retry diagnostics.
Eligibility rules, cache identities and database schema are unchanged.

Live verification update: [results and fixes](../gemini-live-verification.md)
record actual service/quota failures, the 90-second/4,096-token low-thinking
configuration, mandatory quote schema, selected-ID screening, and the
`eligibility-v4-start-flexibility` cache version. Earlier migration details below
are historical where superseded. Production screening remains unverified.

Use `google-genai` and the Gemini Developer API, with `gemini-3.8-flash` as the
default for both preliminary and deeper review. Keep the existing independent
schema/evidence validation and US/international eligibility rules. Public ATS
collection, discovery, scheduling decisions, database schema and cover-letter
generation do not change. Letters remain local deterministic drafts from private
facts and never invoke an AI provider.

Configure `GEMINI_API_KEY`, `GEMINI_PRELIMINARY_MODEL`, `GEMINI_REVIEW_MODEL` and
`GEMINI_MAX_CALLS`. CLI model and request-limit options remain available. An
OpenAI key is never passed to Google. Missing keys preserve reviewable jobs and
monitoring; no SDK client is constructed without an explicit Gemini key.

Structured generation uses `response_mime_type=application/json` and
`response_json_schema`. Accept only a single candidate with `STOP` completion;
blocked, missing, truncated or invalid output remains `needs_review`. Usage
metadata is stored in each result. Input minimization, untrusted-job instructions,
timeouts, output cap, two-attempt transient HTTP retry and persisted daily request
reservations remain in place. SDK retries, function calling and automatic
continuation are disabled, preventing hidden calls outside the request budget.
Injected test clients also receive request-level retry limits.

The prompt cache version changes to `eligibility-v3-gemini`; content/profile/
policy/model keys continue to invalidate results. Historical results are retained,
and the existing daily budget is not reset on migration. No database migration is
needed. There was no OpenAI SDK dependency; httpx remains required by ATS,
discovery, notifications and the Google SDK.

The previous OpenAI `store=false` flag has no direct equivalent in this integration.
Google data handling is governed by the selected service/account terms. Review
the private profile before enabling requests; provider-side retention is not
claimed to be disabled. No live calls were made during migration.

Official references:

- [Google GenAI Python SDK](https://googleapis.github.io/python-genai/)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
