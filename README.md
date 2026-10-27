# JobsFinder.io

A personal job discovery and monitoring project. Phase 1 provides an offline
employer/source registry, SQLite persistence, and an argparse CLI. Phase 2 adds
manual Greenhouse checks and safe posting comparisons. Screening, scheduling,
discovery, and notifications remain deferred.

Phase 3 adds Docker Compose and GitHub Actions CI. It does not add a scheduler
or change collection behavior.

Requires Python 3.12+ and uv. From the repository root:

```powershell
uv sync --locked
uv run alembic upgrade head
uv run jobsfinder-io add-employer --name "Example" --official-domain example.com
uv run jobsfinder-io add-source --employer-id 1 --provider greenhouse --board-identifier example --careers-url https://example.com/careers
uv run jobsfinder-io list-sources
uv run jobsfinder-io list-postings
```

The example employer is synthetic. Substitute the actual employer and board token
for real use. Adding a source creates a `candidate`. After personally verifying
its official employer association and public access, record your confirmation:

```powershell
uv run jobsfinder-io validate-source 1 --confirm-official-association --confirm-public-access
```

This records manual verification without network requests. Repeating it on a
validated source preserves the original validation time. The schema has no field
for a verification note; verification remains the owner's responsibility.

To check that registered, validated source and inspect its saved jobs:

```powershell
uv run jobsfinder-io poll-source --source-id 1
uv run jobsfinder-io list-postings --source-id 1
```

`poll-source` makes public read-only Greenhouse requests without an API key. It
never promotes candidate sources automatically. Candidate and paused sources are
refused without HTTP requests. Each request to check an existing source records a
poll attempt. Source IDs that do not exist return an error.

The first complete successful check is a baseline. Later checks report newly
observed IDs as `new`, meaningful content changes as `updated`, and returning jobs
as `reappeared`. These labels do not claim a job was published today. Jobs absent
from one complete check become `missing_pending`; a second complete miss makes
them `closed`. Failed and partial checks preserve all job data and states.

The collector also looks for `first_published` through individual-job details.
Unknown dates stay unknown. A complete list can succeed with publication lookup
warnings: see `enrichment_failed` in the summary and `date_provenance` in stored
postings. At most 100 detail lookups are attempted per check; failed/deferred
lookups can be retried on later checks. Exit code is 0 for a complete list,
including enrichment warnings, and 1 for a failed, partial, or refused check.

Requests have timeouts, at most three attempts, backoff, and one-second spacing.
The command runs only when invoked; it does not schedule checks or automatically
use the source's configured polling interval. Avoid launching overlapping checks
for the same source. A hard process kill can leave a `running` poll that blocks
later checks; see the [Phase 2 recovery notes](docs/phase-2-greenhouse-design.md).

The default database is `data/jobsfinder.db`, created by Alembic. Database files,
local data, environments, and `.env` files are ignored by Git. Keep private
profiles, resumes, and credentials outside tracked files.

For another database, copy `alembic.ini` to an ignored file such as
`data/local.ini`, set `script_location` to the absolute repository `migrations`
directory, and change `sqlalchemy.url` to `sqlite:///data/other.db`. Then run:

```powershell
uv run alembic -c data/local.ini upgrade head
uv run jobsfinder-io --db data/other.db list-sources
```

`--db` goes before the command. Each command supports `--help`.
`list-postings --source-id 1` inspects stored jobs. Empty lists print no rows.
Duplicate sources return an error without
changing the original record. Matching company names remain separate employers.

Run the offline tests and style checks:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run with Docker Desktop (Linux containers) or Docker Engine with Compose:

```powershell
docker compose build
# Create the data folder once; this PowerShell command also handles an existing folder.
New-Item -ItemType Directory -Force data
docker compose run --rm jobsfinder alembic upgrade head
docker compose run --rm jobsfinder jobsfinder-io --help
docker compose run --rm jobsfinder jobsfinder-io list-sources
```

On Linux/macOS, use `mkdir -p data` instead of `New-Item`. On Linux, also set
`export LOCAL_UID=$(id -u)` and `export LOCAL_GID=$(id -g)` before running Compose
so the non-root container user can write to your directory.

Every existing CLI command works by placing `jobsfinder-io` after the service name:

```powershell
docker compose run --rm jobsfinder jobsfinder-io add-employer --name "Example" --official-domain example.com
docker compose run --rm jobsfinder jobsfinder-io add-source --employer-id 1 --provider greenhouse --board-identifier example --careers-url https://example.com/careers
docker compose run --rm jobsfinder jobsfinder-io validate-source 1 --confirm-official-association --confirm-public-access
docker compose run --rm jobsfinder jobsfinder-io poll-source --source-id 1
docker compose run --rm jobsfinder jobsfinder-io list-postings --source-id 1
```

Use a real, personally verified employer/board before polling; the example is
synthetic. SQLite lives at `./data/jobsfinder.db` on your computer, mounted as
`/app/data/jobsfinder.db`. Removing a container, running `docker compose down`, or
rebuilding the image preserves that directory. Back it up separately and keep
`--db` paths under `data/` when using Docker. To mount another existing directory,
set `JOBSFINDER_DATA_DIR` to its absolute path. No database is copied into the image.

The default container command prints CLI help and exits. Use `docker compose run
--rm` for these one-shot commands; no background service or automatic migrations
run. After code/dependency changes, rebuild and explicitly run `alembic upgrade
head` again. The runtime image installs locked application dependencies without
pytest/Ruff; run tests locally with uv or through CI.

CI runs on pushes to `main` and pull requests. It installs Python and pinned uv,
uses `uv.lock`, runs Ruff and the entire offline test suite (including Alembic
migration tests), then builds the image and exercises container migrations and CLI
persistence across separate containers. It has read-only repository permissions
and does not publish images or deploy anything. See
[Docker/CI design notes](docs/adr/0007-docker-and-ci.md).

Tests migrate temporary databases and never use your registry. Installing
dependencies requires package access once; tests need no internet or API keys.
HTTP responses are mocked, and real HTTP transport is blocked during tests.

Learning checkpoint: trace `cli.main()` → `registry.add_source()` → `JobSource`
in `persistence/models.py`. The CLI opens one transaction, the service checks
inputs, and the database enforces identity and relationships. Success commits;
an exception rolls back. `make_engine()` enables foreign keys on every SQLite
connection. Alembic creates the schema; importing models never creates tables.

For collection, trace `cli.main()` → `poll_source()` in `ingestion/polling.py` →
`GreenhouseCollector.fetch_jobs()` in `sources/greenhouse.py` → `apply_snapshot()`.
The service first commits a running poll record, releases the database connection
while fetching, then commits posting changes and successful poll bookkeeping
together. If that final transaction fails, posting changes roll back and the
service attempts to record the failure separately.

See the [Phase 2 specification and implementation notes](docs/phase-2-greenhouse-design.md),
[documentation index](docs/README.md), and [roadmap](docs/roadmap.md).
