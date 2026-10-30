"""Root-owned Ubuntu controller. No dependencies beyond Python and Docker CLI.

Never source runtime.env here: only Compose loads application credentials.
All installed workers/deployments share one host lock; application locks additionally
protect migrations from manually invoked application commands.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/var/lib/jobsfinder")
UTC = timezone.utc  # Ubuntu 22.04's host Python 3.10; app uses container Python 3.12.
REVISION = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
REPOSITORY = re.compile(r"ghcr\.io/[a-z0-9][a-z0-9._/-]+")


def run(args: list[str], *, env: dict | None = None) -> str:
    """Capture output to avoid logging provider messages or environment secrets."""
    result = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} operation failed (exit {result.returncode})")
    return result.stdout.strip()


def atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        json.dump(value, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


@contextmanager
def lock(path: Path):
    import fcntl

    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def backup(database: Path, destination: Path) -> None:
    """Consistent live-safe SQLite backup; never create a missing source DB."""
    if destination.exists():
        raise ValueError("Backup destination already exists; preserve existing backups")
    with (
        closing(
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as source,
        closing(sqlite3.connect(destination)) as target,
    ):
        source.backup(target)
        if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("Backup integrity check failed")


def compose(state: dict, *command: str) -> str:
    env = os.environ.copy()
    env["JOBSFINDER_RELEASE_IMAGE"] = state["image"]
    args = [
        "docker",
        "compose",
        "--project-name",
        "jobsfinder-production",
        "--env-file",
        "/dev/null",
        "-f",
        state["compose"],
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--name",
        "jobsfinder-task",
        "jobsfinder",
        *command,
    ]
    try:
        return run(args, env=env)
    except RuntimeError as exc:
        # Commands contain no credentials; omit provider/subprocess output.
        raise RuntimeError("Container step failed: " + " ".join(command[:2])) from exc


def available_space(root: Path, database: Path) -> None:
    # Room for download/extraction plus backup and SQLite journal growth.
    required = 3 * 1024**3 + 2 * database.stat().st_size
    if shutil.disk_usage(root).free < required:
        raise RuntimeError("Insufficient disk space: require 3 GiB plus twice DB size")


def update(root: Path = ROOT) -> str:
    if (root / "BLOCKED.json").exists():
        raise RuntimeError(
            "Deployment blocked; inspect BLOCKED.json and recovery guide"
        )
    repository = os.environ.get("JOBSFINDER_IMAGE_REPOSITORY", "")
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("Set lowercase JOBSFINDER_IMAGE_REPOSITORY=ghcr.io/owner/repo")
    database = root / "data/jobsfinder.db"
    if not database.is_file():
        raise RuntimeError("Transfer the existing database before the first deployment")
    available_space(root, database)
    docker_root = Path(run(["docker", "info", "--format", "{{.DockerRootDir}}"]))
    if not docker_root.is_absolute():
        raise RuntimeError("Cannot determine Docker storage location")
    available_space(docker_root, database)
    # Only the CI-approved reference is polled; the resolved digest is used below.
    run(["docker", "pull", "--platform", "linux/amd64", repository + ":production"])
    image = json.loads(run(["docker", "image", "inspect", repository + ":production"]))[
        0
    ]
    revision = (
        image["Config"].get("Labels", {}).get("org.opencontainers.image.revision", "")
    )
    digests = [d for d in image["RepoDigests"] if d.startswith(repository + "@")]
    if not REVISION.fullmatch(revision) or len(digests) != 1:
        raise RuntimeError("Approved image is missing a revision or unambiguous digest")
    digest = digests[0].split("@", 1)[1]
    if not DIGEST.fullmatch(digest) or image["Architecture"] != "amd64":
        raise RuntimeError("Invalid release digest or platform")
    current_path = root / "current.json"
    current = json.loads(current_path.read_text()) if current_path.exists() else None
    if current and current["image"] == digests[0]:
        return "unchanged"
    release = root / "releases" / digest.split(":")[1]
    release.mkdir(parents=True, exist_ok=True)
    # Versioned configuration travels inside the exact approved application image.
    container = run(["docker", "create", digests[0]])
    try:
        run(
            [
                "docker",
                "cp",
                container + ":/app/deploy/compose.yaml",
                str(release / "compose.yaml"),
            ]
        )
    finally:
        run(["docker", "rm", container])
    state = {
        "revision": revision,
        "image": digests[0],
        "digest": digest,
        "compose": str(release / "compose.yaml"),
        "deployed_at": datetime.now(UTC).isoformat(),
    }
    # Both locks match cli.py's paths. Health is called directly while held.
    with ExitStack() as stack:
        for path in [
            database.with_suffix(".run.lock"),
            root / "data/jobsfinder.screening.run.lock",
        ]:
            # Root's deployment lock files must remain writable by UID 1000 workers.
            path.touch(exist_ok=True)
            os.chown(path, 1000, 1000)
            if not stack.enter_context(lock(path)):
                return "application busy"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = root / "backups" / (stamp + ".db")
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup(database, destination)
        # Durable fail-closed marker also survives power loss/SIGKILL during migration.
        marker = {"candidate": state, "previous": current, "backup": str(destination)}
        atomic_json(root / "BLOCKED.json", marker)
        compose(state, "alembic", "upgrade", "head")
        compose(state, "alembic", "check")
        compose(
            state,
            "python",
            "-c",
            "from jobsfinder_io.persistence.database import make_engine; "
            "from jobsfinder_io.operations import health; "
            "e=make_engine('/app/data/jobsfinder.db'); h=health(e); "
            "assert 'source_health' in h; "
            "assert e.connect().exec_driver_sql('PRAGMA quick_check').scalar()=='ok'",
        )
        if current:
            run(
                [
                    "docker",
                    "image",
                    "tag",
                    current["image"],
                    "jobsfinder-retained:previous",
                ]
            )
            atomic_json(root / "previous.json", current)
        run(["docker", "image", "tag", state["image"], "jobsfinder-retained:current"])
        atomic_json(current_path, state)
        (root / "BLOCKED.json").unlink()
    return "deployed " + revision + " " + digest


def tick(root: Path = ROOT) -> str:
    if (root / "BLOCKED.json").exists():
        raise RuntimeError("Workers paused by deployment recovery marker")
    state = json.loads((root / "current.json").read_text())
    # Sequential on the 1 GiB host; reports/monitoring get priority over screening.
    # A monitoring error must not prevent a due screening session, or vice versa.
    failures = []
    for command in ("run-due", "screen-due"):
        try:
            compose(state, "jobsfinder-io", command)
        except RuntimeError:
            failures.append(command)
    if failures:
        raise RuntimeError("Worker failures: " + ", ".join(failures))
    return "tick complete"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["update", "tick", "health"])
    args = parser.parse_args()
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    with lock(ROOT / "host.lock") as acquired:
        if not acquired:
            print("busy; next timer tick will retry")
            return
        try:
            # A daemon-managed container can outlive a killed Docker CLI/host lock.
            # Never overlap with it, even after controller interruption/reboot.
            if run(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=jobsfinder-production",
                ]
            ):
                print("application container still active; retry next tick")
                return
            if args.command == "health":
                state = json.loads((ROOT / "current.json").read_text())
                print(compose(state, "jobsfinder-io", "health"))
            else:
                print(update() if args.command == "update" else tick())
        except (RuntimeError, ValueError, OSError, KeyError) as exc:
            # No subprocess stderr, SMTP errors, tokens or runtime env in logs.
            print(str(exc))
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
