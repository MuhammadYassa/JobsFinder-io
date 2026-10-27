"""Alembic environment for the local SQLite registry."""

from pathlib import Path

from alembic import context
from sqlalchemy.engine import make_url

from jobsfinder_io.persistence.database import make_engine
from jobsfinder_io.persistence.models import Base

config = context.config
url = make_url(config.get_main_option("sqlalchemy.url"))
if url.drivername != "sqlite" or not url.database:
    raise ValueError("Phase 1 migrations require a local SQLite database")

if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    if url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(url.database)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                compare_type=True,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
