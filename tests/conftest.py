from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.database import make_engine

ROOT = Path(__file__).resolve().parents[1]


def migration_config(path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url", f"sqlite:///{path.as_posix()}".replace("%", "%%")
    )
    return config


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "registry.db"
    command.upgrade(migration_config(path), "head")
    engine = make_engine(path)
    yield path, engine
    engine.dispose()


@pytest.fixture
def session(database):
    with Session(database[1]) as session:
        yield session
