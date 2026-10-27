# JobsFinder.io

A personal job discovery and monitoring project. Phase 1 provides an offline
employer/source registry, SQLite persistence, and an argparse CLI. Polling,
screening, scheduling, discovery, and notifications belong to later phases.

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
`list-postings --source-id 1` inspects stored jobs; Phase 1 does not insert or
fetch jobs. Empty lists print no rows. Duplicate sources return an error without
changing the original record. Matching company names remain separate employers.

Run the offline tests and style checks:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests migrate temporary databases and never use your registry. Installing
dependencies requires package access once; tests need no internet or API keys.

Learning checkpoint: trace `cli.main()` → `registry.add_source()` → `JobSource`
in `persistence/models.py`. The CLI opens one transaction, the service checks
inputs, and the database enforces identity and relationships. Success commits;
an exception rolls back. `make_engine()` enables foreign keys on every SQLite
connection. Alembic creates the schema; importing models never creates tables.

See the [Phase 1 specification](docs/phase-1-registry-design.md),
[documentation index](docs/README.md), and [roadmap](docs/roadmap.md).
