from datetime import UTC

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.database import make_engine
from jobsfinder_io.persistence.models import Employer, JobSource
from jobsfinder_io.registry import (
    RegistryError,
    add_employer,
    add_source,
    list_postings,
    list_sources,
    validate_source,
)


def source(session, employer_id, token="example", **kwargs):
    return add_source(
        session,
        employer_id,
        "greenhouse",
        token,
        "https://example.com/careers",
        **kwargs,
    )


def test_restart_and_multiple_sources(database):
    path, engine = database
    with Session(engine) as session, session.begin():
        employer = add_employer(session, " Example ", "EXAMPLE.COM.")
        source(session, employer.id)
        source(session, employer.id, "example-eu")
    engine.dispose()
    reopened = make_engine(path)
    try:
        with Session(reopened) as session:
            sources = list_sources(session)
            assert len(sources) == 2
            assert sources[0].employer.name == "Example"
            assert sources[0].employer.official_domain == "example.com"
            assert sources[0].created_at.tzinfo == UTC
            assert sources[0].employer.updated_at.tzinfo == UTC
            assert sources[0].status == "candidate"
            assert sources[0].validated_at is None
            assert sources[0].last_success_at is None
            assert sources[0].last_attempt_at is None
            assert sources[0].consecutive_failures == 0
            assert sources[0].poll_interval_minutes == 60
            assert sources[0].api_endpoint.endswith("/example/jobs")
            assert list_postings(session) == []
    finally:
        reopened.dispose()


def test_duplicate_and_retry_do_not_reassign_source(session):
    first = add_employer(session, "Example")
    second = add_employer(session, "Example")
    assert first.id != second.id
    original = source(session, first.id)
    for _ in range(2):
        with pytest.raises(RegistryError, match="already registered"):
            add_source(
                session, second.id, " GreenHouse ", " example ", "https://example.com"
            )
    assert list_sources(session) == [original]
    assert original.employer_id == first.id
    # Duplicate handling leaves the enclosing transaction usable.
    source(session, first.id, "another")
    session.commit()
    assert session.scalar(select(func.count()).select_from(JobSource)) == 2


@pytest.mark.parametrize(
    "name,domain",
    [(" ", None), ("X", "https://example.com"), ("X", "bad/path"), ("X", "")],
)
def test_invalid_employer(session, name, domain):
    with pytest.raises(RegistryError):
        add_employer(session, name, domain)
    assert session.scalar(select(func.count()).select_from(Employer)) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "unknown"),
        ("board_identifier", ""),
        ("board_identifier", "https://example.com"),
        ("board_identifier", "a/b"),
        ("careers_url", "javascript:alert(1)"),
        ("careers_url", "https://user:secret@example.com"),
        ("careers_url", "https://[broken"),
        ("careers_url", "https://example.com:bad"),
        ("poll_interval_minutes", 0),
        ("poll_interval_minutes", -1),
        ("employer_id", 999),
    ],
)
def test_invalid_source(session, field, value):
    employer = add_employer(session, "Example")
    kwargs = {
        "employer_id": employer.id,
        "provider": "greenhouse",
        "board_identifier": "example",
        "careers_url": "https://example.com",
    }
    kwargs[field] = value
    with pytest.raises(RegistryError):
        add_source(session, **kwargs)
    assert list_sources(session) == []


def test_manual_validation_is_explicit_and_idempotent(session):
    employer = add_employer(session, "Example")
    entry = source(session, employer.id)
    for official, public in [(False, False), (True, False), (False, True)]:
        with pytest.raises(RegistryError):
            validate_source(
                session,
                entry.id,
                official_association_confirmed=official,
                public_access_confirmed=public,
            )
        assert entry.status == "candidate"
    validated = validate_source(
        session,
        entry.id,
        official_association_confirmed=True,
        public_access_confirmed=True,
    )
    timestamp = validated.validated_at
    assert timestamp.tzinfo == UTC
    validate_source(
        session,
        entry.id,
        official_association_confirmed=True,
        public_access_confirmed=True,
    )
    assert validated.validated_at == timestamp
    with pytest.raises(RegistryError, match="does not exist"):
        validate_source(
            session,
            999,
            official_association_confirmed=True,
            public_access_confirmed=True,
        )
    with pytest.raises(RegistryError, match="does not exist"):
        list_postings(session, 999)


def test_exception_rolls_back_whole_transaction(database):
    _, engine = database
    with pytest.raises(RuntimeError), Session(engine) as session, session.begin():
        employer = add_employer(session, "Will roll back")
        source(session, employer.id)
        raise RuntimeError("synthetic crash")
    with Session(engine) as session, session.begin():
        assert list_sources(session) == []
        assert session.scalar(select(func.count()).select_from(Employer)) == 0
        employer = add_employer(session, "Retry")
        source(session, employer.id)


def test_source_savepoint_does_not_commit_outer_transaction(database):
    _, engine = database
    with Session(engine) as session, session.begin():
        employer_id = add_employer(session, "Existing employer").id
    with pytest.raises(RuntimeError), Session(engine) as session, session.begin():
        source(session, employer_id)
        raise RuntimeError("crash after releasing the source savepoint")
    with Session(engine) as session:
        assert list_sources(session) == []
