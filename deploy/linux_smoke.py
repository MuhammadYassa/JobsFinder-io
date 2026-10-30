"""Offline Linux check; mount deploy/ read-only at /verification."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/verification")
import host  # noqa: E402

os.umask(0o077)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    with host.lock(root / "host.lock") as first:
        assert first
        with host.lock(root / "host.lock") as second:
            assert not second
    with host.lock(root / "host.lock") as recovered:
        assert recovered
    source = root / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE retained (id INTEGER)")
        connection.execute("INSERT INTO retained VALUES (42)")
        connection.commit()
        host.backup(source, root / "backup.db")
    with sqlite3.connect(root / "backup.db") as connection:
        assert connection.execute("SELECT id FROM retained").fetchall() == [(42,)]
    host.atomic_json(root / "state.json", {"image": "test-digest"})
    assert json.loads((root / "state.json").read_text())["image"] == "test-digest"
    assert (root / "state.json").stat().st_mode & 0o777 == 0o600
print("Linux host locks, release-state durability and SQLite WAL backup passed")
