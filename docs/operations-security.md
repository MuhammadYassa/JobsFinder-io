# Operations, Cost, and Security (Proposed v0.1)

## Scheduling

- Collector: configurable **hourly target** for healthy, supported public boards; tolerate source-specific throttling.
- Employer discovery: lower-frequency scheduled passes (initially daily) with rotating regions/industries.
- Fast alerts: trigger on qualifying newly observed IDs after preliminary screening; do not block for letter generation.
- US and international reports: target 10:00 and 20:00 in `America/New_York`, with correct daylight-saving handling.
- All persistent timestamps: UTC with timezone info. Scheduler execution timestamps are not employer publication times.

## Reliability

- Bounded request concurrency, explicit timeout, HTTP 429 backoff, exponential retries with jitter, per-provider throttling.
- Poll runs explicitly track `complete_success`, `partial`, `failed`; missing jobs from incomplete runs cannot be marked closed.
- Reentrant/idempotent workers: replay of a fetch, screening, or notification task should not duplicate records or alerts.
- Persistent source health: last complete check, failures in a row, last error, last change and stale-source age.
- Conservative removals, confirmed/reappeared tracking and regular backup/restore tests.
- Use fixtures before live tests. Never load-test public career APIs without permission.

## Cost controls

- No LLM calls for unchanged jobs unless the policy/model version changes or a manual reevaluation is requested.
- Account for employer discovery API/web search charges separately from LLM processing tokens.
- Set monthly and per-day budget limits, log calls/model and tokens, and fail to `needs_review` if limits are reached.
- Track queue size so cheaper screening doesn't silently leave high-priority findings unsent.
- Deployment decision is pending; local prototype incurs no mandatory hosting charge but cannot guarantee 24/7 availability.

## Privacy and access

- Repository is public. **Do not commit** personal profile, nationality/immigration records, resumes, application notes, API keys, database files, .env secrets, raw downloaded private data, or identifying log samples.
- Introduce `.env.example` with placeholders only, and amend existing `.gitignore` at implementation time; keep per-profile search configuration outside tracked files or in encrypted managed secrets.
- Minimize profile data sent to third-party models; keep records locally/private at rest and limit log exposure.
- Restrict collectors to public GET/read-only data; do not bypass login walls, anti-bot controls, robots/terms, CAPTCHAs or access restrictions.
- Prevent SSRF by validating allowed hosts/endpoints and disallowing arbitrary untrusted internal-network URLs before fetching.
- No auto-applications, contact, or resume uploads. Delivery permissions should be separate and explicit.

## Observability

- Structured, non-sensitive logs: source ID, run ID, duration, success, pages and post count, new/updated/missing counts, queue length, classifications, alert idempotency state, costs.
- Daily health report: checked vs due sources, oldest last-success timestamp, repeated errors, currently unprocessed candidates, actual costs.
- Weekly quality sample: screening false negatives and time-to-first-seen where source publication data is credible.

## Deployment choices to evaluate later

- Initial CLI and local SQLite for proof of correctness.
- For hourly unattended checks, choose a reliable always-on service or scheduler+hosted database. GitHub Actions is convenient but schedules can be delayed; evaluate scheduling reliability, secrets, rate limits, and persistent state before choosing it.
- Choose PostgreSQL when the workload needs a reliable multi-run persistent database and concurrency/remote access. Do not migrate only for complexity's sake.
