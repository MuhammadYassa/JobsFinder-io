# JobsFinder.io

Personal employer discovery, public career-board monitoring, and evidence-grounded
job screening. Python 3.12+, uv, SQLAlchemy, Alembic, SQLite, argparse and Docker.
It generates personal job reports and alerts; it never submits applications.
Development is complete; Azure hosting and permanent schedules still need setup.
Monitoring, email and reports run independently of optional Gemini screening.

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

For limited screening use `screen --posting-id ID --max-calls LIMIT`
with the intended `--db` and `--profile`; repeat `--posting-id` to select a small batch.
The [final ten-job pilot](docs/activation-pilot.md) passed and the owner approved
enabled screening configuration. Earlier service/quota reports remain historical.

`screen` now batches up to 10 jobs per request by default. Separate `screen-due`
sessions target 9:30 AM/7:30 PM New York. AI defaults to true/20 calls per Pacific
day with two reserved calls and eight batches per session. No host schedule has
been installed. See [batch configuration](docs/gemini-batch-screening.md).

`run-due` performs one scheduled tick. Run every five minutes on an always-on
host; per-source intervals normally permit hourly polls. Discovery runs at 6 AM;
US/international reports run at 10 AM/8 PM America/New_York with DST handling.
Persistent receipts prevent repeats; an OS lock prevents overlapping CLI work
and enables interrupted-poll recovery. Network calls hold no DB transaction.
`run-due` never invokes Gemini; the separate `screen-due` command does. Explicitly
set `GEMINI_BATCH_ENABLED=false` and `GEMINI_MAX_CALLS=0` to disable AI.

Screening batches jobs with separate US/international policy outcomes, exact
evidence quotes, private profile/model/prompt/validator version caching and a
durable daily request cap. Missing credentials and ambiguous evidence remain
reviewable. Define your actual education, experience, availability and immigration
constraints in the private profile; see [screening design](docs/ai-screening.md).
The source code contains no personal profile.

Screening uses the official `google-genai` SDK with `gemini-3.5-flash-lite` by default.
Configure `GEMINI_BATCH_MODEL`, `GEMINI_DAILY_LIMIT`, and `GEMINI_MAX_CALLS`
as needed; retain the retry reserve and adaptive token limits. See
[ADR 0009](docs/adr/0009-gemini-screening.md).

Seven-day non-AI reports include baseline and missed discoveries, distinguish
source publication from discovery and uncertain freshness, and quote requirements.
Scheduled non-AI reports do not rank eligibility, verify sponsorship, or generate cover letters.
Local files remain available, and SMTP sends grouped alerts/reports exclusively
to your configured personal address. Durable receipts prevent unchanged repeats;
ambiguous delivery requires review. No employer messages or applications are sent.

## Docker and operation

```sh
mkdir -p data/private
# New setup only: preserve an existing .env and its production data mount.
cp -n .env.example .env
docker compose build
docker compose run --rm jobsfinder alembic upgrade head
docker compose run --rm jobsfinder jobsfinder-io health
```

On PowerShell use `New-Item -ItemType Directory -Force data/private` and
copy `.env.example` only if `.env` does not already exist. Compose reads `.env`; local uv commands use shell
environment variables or explicit CLI options (no automatic dotenv loading).
Configure private files before `run-due`. The bind-mounted data directory survives
container upgrades. Set Linux UID/GID as described in the deployment guide.

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM`, and your personal `SMTP_TO` for email.
No credentials are needed for monitoring, imported-page discovery or local reports.
Search remains optional. AI is enabled in configuration; installing its host
schedule remains a deployment step. Monitoring/reports work without an AI key.

[Deployment instructions](docs/deployment.md#azure-deployment-readiness) include Azure readiness, cron, privacy, persistent
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
claim. Retained acceptance evidence covers [non-AI operation](docs/non-ai-final-verification.md),
[screening accuracy](docs/flash-lite-final-accuracy.md), and the
[final pilot](docs/activation-pilot.md). Those records do not verify the Azure host.

Learning checkpoint: trace `cli.main()` → `operations.run_due()` →
`ingestion.polling.poll_source()` → `apply_snapshot()`. Then follow
`reporting.non_ai.generate_reports()` → `delivery.enqueue_email()` →
`delivery.deliver_pending()`. TaskRun stores each grouped message and Delivery
reserves each posting revision. Those receipts make repeated ticks safe.

See [documentation index](docs/README.md) and [ADR 0008](docs/adr/0008-integrated-personal-workflow.md)
for current architecture and tradeoffs.
