from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.database import make_engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def reject_request(*args, **kwargs):
        pytest.fail("Tests must mock HTTP; live requests are forbidden")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_request)


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
