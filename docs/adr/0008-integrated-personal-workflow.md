# ADR 0008 — Complete the personal monitoring workflow

> Provider update: [ADR 0009](0009-gemini-screening.md) supersedes the OpenAI
> portions below. They record the historical implementation; current screening
> uses the Google GenAI SDK and Gemini.

- Status: Accepted by the owner's complete-system implementation request
- Date: 2026-10-27

Retain the Python modular monolith, SQLite, SQLAlchemy, Alembic, argparse, uv and
Docker. Extend the completed foundation with public Lever (global/EU) and Ashby
adapters, candidate-page discovery and optional Brave search, structured OpenAI
screening, local reports/letters, optional Telegram, and cron-compatible ticks.
No service is deployed or schedule installed during development.

The initial four-table migration remains intact. A second migration adds four
durable workflow tables (screening_results, deliveries, discovery_attempts,
task_runs) and posting locations/revisions/change times. These are needed for
audit, caching, restart recovery and delivery deduplication. Historical screening
results are retained; provider IDs remain the primary posting identity.

One local OS lock serializes CLI workflows, releases on hard process exit, and
allows interrupted running work to be recovered. HTTP never holds a database
transaction. Operate one scheduler host per SQLite file; network filesystems and
direct simultaneous service calls are unsupported. Migrations require stopped
writers, use a dedicated FK-disabled connection for SQLite table rebuilds, and
check foreign keys before completion.

Daily discovery uses imported official career pages without a paid key. Optional
search expands the candidate queue; an unknown domain requires confirmation
before automatic activation. This trades unattended breadth for defensible
employer association. Robots/access failures remain failures, never bypasses.

OpenAI calls use the documented Responses structured-output interface, bounded
requests/output and durable UTC-day request caps. Private profile changes
invalidate results. Missing credentials, uncertain eligibility and malformed AI
results remain reviewable. A request cap is not a dollar budget.

Seven-day reports run at 10:00/20:00 America/New_York via host cron ticks; local
files are the default delivery channel. Exact official links within the same
employer can suppress duplicates; different requisitions are retained.
Telegram POST acknowledgement uncertainty is persisted and never auto-replayed.
Cover letters are local deterministic drafts grounded in private facts.

Official interfaces:

- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby public postings](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage)
- [Brave web search](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)

## Non-AI operating mode, accepted by the owner's production-completion request

Unattended ticks now explicitly omit screening and produce conservative reports
without a private AI profile. SMTP to one configured personal address replaces
Telegram in this operating path. Existing task/delivery tables retain grouped
outbox content, attempts and per-revision reservations; ambiguous acceptance is
never automatically replayed. No schema or additional service is introduced.
Discovery runs from 06:00 New York using persistent bounded cursors, imports and
trusted directories; optional search remains opt-in. Reports run at 10:00/20:00.
Local-only verification uses separate scheduler receipts, preserving later email
delivery. See [deployment](../deployment.md) and
[Python SMTP](https://docs.python.org/3/library/smtplib.html).
