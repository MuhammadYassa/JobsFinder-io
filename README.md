# JobsFinder.io

Personal employer discovery, public career-board monitoring, and evidence-grounded
job screening. Python 3.12+, uv, SQLAlchemy, Alembic, SQLite, argparse and Docker.
It generates personal job reports and alerts; it never submits applications.
The current unattended workflow runs without AI.

Supports Greenhouse, Lever (global/EU), and Ashby. Complete polls preserve source
identity, locations, separate publication/update/discovery/verification times,
content revisions and historical jobs. First scans are baselines. Two complete
successful absences close a posting; failed or incomplete polls never do.

## Local setup

```sh
uv sync --locked
uv run alembic upgrade head
uv run jobsfinder-io --help
uv run jobsfinder-io health
```

The default database is `data/jobsfinder.db`. `--db PATH` precedes the command.
Migrate explicitly before operating; stop all writers before migrations/upgrades.

Register a real employer and board, then confirm its public official association:

```sh
uv run jobsfinder-io add-employer --name "Example" --official-domain example.com
uv run jobsfinder-io add-source --employer-id 1 --provider greenhouse --board-identifier example --careers-url https://example.com/careers
uv run jobsfinder-io validate-source 1 --confirm-official-association --confirm-public-access
uv run jobsfinder-io poll-source --source-id 1
uv run jobsfinder-io list-postings
```

These identifiers are synthetic. Supported provider names: `greenhouse`, `lever`,
`lever_eu`, `ashby`. No API key is required for public ATS collection.

## Discovery, screening and delivery

Put private JSON configuration in ignored `data/private/`. Candidate format:

```json
[{"name":"Example","careers_url":"https://example.com/careers"}]
```

Import only official employer pages. Discovery checks robots rules and outbound
ATS links, validates complete boards, and records successful/failed checks.
Optional Brave search can expand the candidate queue; unknown search domains
require confirmation before activation. Coverage depends on supplied pages and
queries. See [discovery configuration](src/jobsfinder_io/discovery/README.md).

```sh
uv run jobsfinder-io discover --candidates data/private/candidates.json
uv run jobsfinder-io poll-due
uv run jobsfinder-io report --local-only
uv run jobsfinder-io test-email
uv run jobsfinder-io notify
uv run jobsfinder-io run-due --candidates data/private/candidates.json
```

For limited screening use `screen --posting-id 34 --posting-id 68 --max-calls 8`
with the intended `--db` and `--profile`; repeated IDs select a small batch.
[Live Gemini verification](docs/gemini-live-verification.md) found service/quota
failures, so production AI screening has not yet passed acceptance.

`screen` now batches up to 10 jobs per request by default. Separate `screen-due`
sessions target 9:30 AM/7:30 PM New York and remain disabled. See
[batch configuration and later live-test instructions](docs/gemini-batch-screening.md).

`run-due` performs one scheduled tick. Run every five minutes on an always-on
host; per-source intervals normally permit hourly polls. Discovery runs at 6 AM;
US/international reports run at 10 AM/8 PM America/New_York with DST handling.
Persistent receipts prevent repeats; an OS lock prevents overlapping CLI work
and enables interrupted-poll recovery. Network calls hold no DB transaction.
These operating commands never invoke Gemini. Leave `GEMINI_MAX_CALLS=0`.

Screening uses separate US/international policies, two structured Google Gemini review
stages, exact evidence quotes, private profile/model/prompt version caching and a
durable daily request cap. Missing credentials and ambiguous evidence remain
reviewable. Define your actual education, experience, availability and immigration
constraints in the private profile; see [screening design](docs/ai-screening.md).
The source code contains no personal profile.

Screening uses the official `google-genai` SDK with `gemini-3.5-flash-lite` by default.
Configure `GEMINI_PRELIMINARY_MODEL`, `GEMINI_REVIEW_MODEL`, and `GEMINI_MAX_CALLS`
as needed. The OpenAI integration has been replaced; see
[ADR 0009](docs/adr/0009-gemini-screening.md).

Seven-day non-AI reports include baseline and missed discoveries, distinguish
source publication from discovery and uncertain freshness, and quote requirements.
They do not rank eligibility, verify sponsorship, or generate cover letters.
Local files remain available, and SMTP sends grouped alerts/reports exclusively
to your configured personal address. Durable receipts prevent unchanged repeats;
ambiguous delivery requires review. No employer messages or applications are sent.

## Docker and operation

```sh
mkdir -p data/private
cp .env.example .env
docker compose build
docker compose run --rm jobsfinder alembic upgrade head
docker compose run --rm jobsfinder jobsfinder-io health
```

On PowerShell use `New-Item -ItemType Directory -Force data/private` and
`Copy-Item .env.example .env`. Compose reads `.env`; local uv commands use shell
environment variables or explicit CLI options (no automatic dotenv loading).
Configure private files before `run-due`. The bind-mounted data directory survives
container upgrades. Set Linux UID/GID as described in the deployment guide.

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM`, and your personal `SMTP_TO` for email.
No credentials are needed for monitoring, imported-page discovery or local reports.
Search remains optional; AI stays disabled in unattended operation.

[Deployment instructions](docs/deployment.md) include cron, privacy, persistent
storage, backups and recovery. No schedule is installed, image published, or
external infrastructure deployed by the project. CI validates the app and Docker;
it never operates the persistent production database.

## Validation and learning

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests migrate temporary databases and block live HTTP. The end-to-end test uses
synthetic discovery pages, ATS data and AI responses; it is not a live-production
claim. See [QA review](docs/qa-review.md) and [build progress](docs/build-plan.md).

Learning checkpoint: trace `cli.main()` → `operations.run_due()` →
`ingestion.polling.poll_source()` → `apply_snapshot()`. Then follow
`reporting.non_ai.generate_reports()` → `delivery.enqueue_email()` →
`delivery.deliver_pending()`. TaskRun stores each grouped message and Delivery
reserves each posting revision. Those receipts make repeated ticks safe.

See [documentation index](docs/README.md) and [ADR 0008](docs/adr/0008-integrated-personal-workflow.md)
for current architecture and tradeoffs.
