# ADR 0007 — Local Docker packaging and GitHub Actions CI

- **Status:** Accepted — requested by the owner as Phase 3

## Context and decision

The completed registry and Greenhouse collector need reproducible local packaging
and automated checks. Phase 3 now covers Docker and CI. The earlier roadmap's
additional ATS adapters and scheduling are deferred, not authorized by this slice.

Use one Linux Python 3.12 slim container with pinned uv 0.13.6. Install application
dependencies with `uv sync --locked --no-dev`, then install the app non-editably.
Use a BuildKit cache for downloads; copy only application/build/migration inputs.
The runtime process runs as a non-root user. Python's minor-version/base-OS tag
can receive security updates on a rebuild; this is dependency reproducibility,
not a claim that image bytes remain identical forever.

Compose has a single `jobsfinder` service. Its default command prints help; users
replace it with either `jobsfinder-io ...` or `alembic ...` through `compose run`.
No entrypoint script, automatic migration, restart loop, server, port, scheduler,
or database service is needed. Runtime commands use the installed virtualenv
directly and do not resolve or download dependencies.

Bind-mount an existing local `./data` directory to `/app/data`, preserving the
existing relative SQLite path. An optional `JOBSFINDER_DATA_DIR` selects a separate
existing directory for testing. `LOCAL_UID`/`LOCAL_GID` default to 1000 and can match
the host owner on Linux. Require the directory to exist to avoid Docker creating
a root-owned host directory. No application tables or migrations change.

GitHub Actions runs on `main` pushes and pull requests, using Ubuntu, supported
checkout/setup-python/setup-uv actions pinned to reviewed release commits, Python
from `.python-version`, and uv 0.13.6. Install the locked dev environment and run
all tests and Ruff checks. Build the image with Compose, then check migrations,
schema parity, non-root execution, and registry persistence across disposable
containers using a temporary bind directory. HTTP tests remain mocked and real
HTTP transport is blocked by the existing pytest fixture. No tokens, registry
login, image publication, workflow dispatch, or deployment step is added.

## Consequences

- Local data stays outside the image and survives container removal/rebuilds.
  The host directory still needs its own backups; bind mounts are not backups.
- Docker commands require a working Linux Docker engine. Users create the data
  directory once and explicitly run migrations. Windows/macOS use Docker Desktop;
  Linux users may need to set host UID/GID before running commands.
- Runtime images omit test tools and fixtures. CI runs the full suite in its host
  Python environment and checks the actual built image separately.
- Builds and dependency installation need access to package/image registries;
  tests and container smoke checks do not call live employer APIs.
- uv and action pins should be reviewed when updating tooling. The container's
  default is intentionally short-lived because this is a manual CLI application.

## Official references

- [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)
- [uv GitHub Actions integration](https://docs.astral.sh/uv/guides/integration/github/)
- [Compose run](https://docs.docker.com/reference/cli/docker/compose/run/)
- [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
