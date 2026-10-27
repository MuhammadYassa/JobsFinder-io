# JobsFinder.io

A personal job discovery and monitoring project. Phase 1 provides an offline
employer/source registry, SQLite persistence, and an argparse CLI. Phase 2 adds
manual Greenhouse checks and safe posting comparisons. Screening, scheduling,
discovery, and notifications remain deferred.

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
