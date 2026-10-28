from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.database import make_engine

ROOT = Path(__file__).resolve().parents[1]


def gemini_client(*, transport, attempts=1):
    """Exercise the real SDK's serialization over a fully mocked HTTP transport."""
    return genai.Client(
        api_key="synthetic-placeholder",
        vertexai=False,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=attempts),
            client_args={"transport": transport, "trust_env": False},
            async_client_args={"trust_env": False},
        ),
    )


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
