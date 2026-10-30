"""Production controller tests never use Docker, SMTP, AI, or real databases."""

import importlib.util
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "deployment_host", Path(__file__).resolve().parents[1] / "deploy/host.py"
)
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)

REPO = "ghcr.io/example/jobsfinder"
IMAGE = REPO + "@sha256:" + "a" * 64
SHA = "b" * 40


@contextmanager
def unlocked(path):
    yield True


@pytest.fixture
def installation(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    with sqlite3.connect(tmp_path / "data/jobsfinder.db") as database:
        database.execute("CREATE TABLE preserved (id INTEGER PRIMARY KEY)")
        database.execute("INSERT INTO preserved VALUES (42)")
    monkeypatch.setenv("JOBSFINDER_IMAGE_REPOSITORY", REPO)
    monkeypatch.setattr(host, "lock", unlocked)
    monkeypatch.setattr(host.os, "chown", lambda *args: None, raising=False)
    monkeypatch.setattr(
        host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3)
    )
    commands = []

    def docker(args, **kwargs):
        commands.append(args)
        if args[1] == "info":
            return str(tmp_path)
        if args[1:3] == ["image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Config": {
                            "Labels": {"org.opencontainers.image.revision": SHA}
                        },
                        "RepoDigests": [IMAGE],
                        "Architecture": "amd64",
                    }
                ]
            )
        if args[1] == "create":
            return "synthetic-container"
        if args[1] == "cp":
            Path(args[-1]).write_text("services: {}")
        return ""

    monkeypatch.setattr(host, "run", docker)
    return tmp_path, commands


def test_deployment_backup_migration_health_and_atomic_selection(installation):
    root, calls = installation
    assert host.update(root).startswith("deployed " + SHA)
    state = json.loads((root / "current.json").read_text())
    assert state["image"] == IMAGE
    assert Path(state["compose"]).is_file()
    assert not (root / "BLOCKED.json").exists()
    backups = list((root / "backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as database:
        assert database.execute("SELECT id FROM preserved").fetchall() == [(42,)]
    migrations = next(
        i for i, c in enumerate(calls) if c[-3:] == ["alembic", "upgrade", "head"]
    )
    health = next(i for i, c in enumerate(calls) if "-c" in c)
    assert migrations < health
    calls.clear()
    assert host.update(root) == "unchanged"
    assert all(c[1] not in {"compose", "create"} for c in calls)
    assert len(list((root / "backups").glob("*.db"))) == 1


@pytest.mark.parametrize("failure", ["upgrade", "check", "health"])
def test_failed_deployment_blocks_workers_and_preserves_old_state(
    installation, monkeypatch, failure
):
    root, _ = installation
    old = {"image": REPO + "@sha256:" + "c" * 64, "compose": "previous.yaml"}
    host.atomic_json(root / "current.json", old)

    def failing_compose(state, *args):
        if failure in args or (failure == "health" and args[0] == "python"):
            raise RuntimeError("synthetic deployment failure")

    monkeypatch.setattr(host, "compose", failing_compose)
    with pytest.raises(RuntimeError):
        host.update(root)
    assert json.loads((root / "current.json").read_text()) == old
    marker = json.loads((root / "BLOCKED.json").read_text())
    assert Path(marker["backup"]).is_file()
    assert marker["previous"] == old
    with pytest.raises(RuntimeError, match="paused"):
        host.tick(root)
    with pytest.raises(RuntimeError, match="blocked"):
        host.update(root)


def test_previous_working_release_retained(installation):
    root, _ = installation
    old = {"image": REPO + "@sha256:" + "c" * 64, "compose": "previous.yaml"}
    host.atomic_json(root / "current.json", old)
    host.update(root)
    assert json.loads((root / "previous.json").read_text()) == old


def test_insufficient_disk_prevents_pull(installation, monkeypatch):
    root, calls = installation
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(RuntimeError, match="disk space"):
        host.update(root)
    assert not calls


def test_missing_database_is_never_created(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSFINDER_IMAGE_REPOSITORY", REPO)
    with pytest.raises(RuntimeError, match="existing database"):
        host.update(tmp_path)
    assert not (tmp_path / "data/jobsfinder.db").exists()


def test_backup_refuses_overwrite_and_missing_source(tmp_path):
    source = tmp_path / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        host.backup(source, tmp_path / "new-backup.db")
    assert not source.exists()
    protected = tmp_path / "protected.db"
    protected.write_bytes(b"preserve this backup")
    with pytest.raises(ValueError, match="already exists"):
        host.backup(source, protected)
    assert protected.read_bytes() == b"preserve this backup"


def test_docker_disk_checked_before_pull(installation, monkeypatch):
    root, calls = installation
    storage = root / "image-storage"
    storage.mkdir()
    original = host.run

    def run(args, **kwargs):
        if args[1] == "info":
            return str(storage)
        return original(args, **kwargs)

    monkeypatch.setattr(host, "run", run)
    monkeypatch.setattr(
        host.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=1 if path == storage else 10 * 1024**3),
    )
    with pytest.raises(RuntimeError, match="disk space"):
        host.update(root)
    assert not any(c[1] == "pull" for c in calls)


def test_busy_application_lock_prevents_migration(installation, monkeypatch):
    root, calls = installation

    @contextmanager
    def busy(path):
        yield False

    monkeypatch.setattr(host, "lock", busy)
    assert host.update(root) == "application busy"
    assert not (root / "current.json").exists()
    assert not any(c[1] == "compose" for c in calls)


def test_worker_serializes_monitoring_and_ai_and_isolates_errors(
    installation, monkeypatch
):
    root, _ = installation
    host.atomic_json(root / "current.json", {"image": IMAGE, "compose": "test.yaml"})
    calls = []

    def compose(state, *args):
        calls.append(args[-1])
        if args[-1] == "run-due":
            raise RuntimeError("synthetic failure")

    monkeypatch.setattr(host, "compose", compose)
    with pytest.raises(RuntimeError, match="run-due"):
        host.tick(root)
    assert calls == ["run-due", "screen-due"]


def test_backup_captures_committed_wal_data(tmp_path):
    source = tmp_path / "live.db"
    target = tmp_path / "backup.db"
    with sqlite3.connect(source) as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("CREATE TABLE records (id INTEGER)")
        database.execute("INSERT INTO records VALUES (7)")
        database.commit()
        host.backup(source, target)
    with sqlite3.connect(target) as copied:
        assert copied.execute("SELECT id FROM records").fetchall() == [(7,)]


def test_subprocess_failure_never_logs_secrets(monkeypatch):
    monkeypatch.setattr(
        host.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="SECRET", stderr="SECRET"),
    )
    with pytest.raises(RuntimeError) as error:
        host.run(["docker", "login"])
    assert "SECRET" not in str(error.value)


def test_host_lock_is_nonblocking_on_linux(tmp_path):
    pytest.importorskip("fcntl")
    with host.lock(tmp_path / "host.lock") as first:
        assert first
        with host.lock(tmp_path / "host.lock") as second:
            assert not second
