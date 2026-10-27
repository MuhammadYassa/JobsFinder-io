"""SQLite connections with foreign keys enabled on every connection."""

from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event


def make_engine(path: str | Path) -> Engine:
    """Open a local SQLite file; schema setup is always done by Alembic."""
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"timeout": 5, "autocommit": False},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _record) -> None:
        # Python 3.12's modern transaction mode keeps savepoints inside the
        # outer transaction. PRAGMA changes need autocommit temporarily enabled.
        previous_autocommit = connection.autocommit
        connection.autocommit = True
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            connection.autocommit = previous_autocommit

    return engine
