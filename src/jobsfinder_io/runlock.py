"""Process-scoped advisory lock, released by the OS even after a hard kill."""

from contextlib import contextmanager
from pathlib import Path


class RunInProgress(RuntimeError):
    pass


@contextmanager
def database_run_lock(database_path: str | Path):
    """Serialize workflow commands without holding a SQLite transaction over HTTP.

    The lock file is deliberately retained: deleting it permits inode races.
    All production commands must share the same local database and lock directory.
    """
    import os

    lock_path = Path(database_path).resolve().with_suffix(".run.lock")
    with lock_path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RunInProgress("Another workflow is using this database") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
