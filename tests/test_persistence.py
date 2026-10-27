from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import migration_config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, StatementError

from jobsfinder_io.persistence.models import Base, Employer, JobSource, PollRun, Posting
from jobsfinder_io.registry import add_employer


def seed(session):
    employer = add_employer(session, "Example")
    source = JobSource(
        employer_id=employer.id,
        provider="greenhouse",
        board_identifier="example",
        careers_url="https://example.com",
        api_endpoint="https://example.com/jobs",
    )
    session.add(source)
    session.flush()
    return source


def posting(source_id, **kwargs):
    now = datetime.now(UTC)
    fields = {
        "source_id": source_id,
        "external_posting_id": "123",
        "title": "Engineer",
        "canonical_job_url": "https://example.com/job",
        "apply_url": "https://example.com/apply",
        "description_text": "Synthetic fixture",
        "date_provenance": "unknown",
        "first_seen_at": now,
        "last_seen_at": now,
        "content_hash": "abc",
    }
    fields.update(kwargs)
    return Posting(**fields)


def test_migration_schema_parity_downgrade_and_repeat_upgrade(database):
    path, engine = database
    expected = {"employers", "job_sources", "postings", "poll_runs", "alembic_version"}
    assert set(inspect(engine).get_table_names()) == expected
    with engine.connect() as connection:
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )
    command.upgrade(migration_config(path), "head")
    command.check(migration_config(path))
    command.downgrade(migration_config(path), "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(migration_config(path), "head")
    assert set(inspect(engine).get_table_names()) == expected


@pytest.mark.parametrize(
    "table,sql",
    [
        ("job_sources", "UPDATE job_sources SET employer_id = 999"),
        ("job_sources", "UPDATE job_sources SET status = 'invalid'"),
        ("job_sources", "UPDATE job_sources SET status = 'validated'"),
        ("job_sources", "UPDATE job_sources SET provider = 'unknown'"),
        ("job_sources", "UPDATE job_sources SET board_identifier = ''"),
        ("job_sources", "UPDATE job_sources SET poll_interval_minutes = 0"),
        ("job_sources", "UPDATE job_sources SET consecutive_failures = -1"),
        ("postings", "UPDATE postings SET status = 'invalid'"),
        ("postings", "UPDATE postings SET source_id = 999"),
        ("postings", "UPDATE postings SET external_posting_id = ''"),
        ("postings", "UPDATE postings SET title = NULL"),
        ("postings", "UPDATE postings SET last_seen_at = '2000-01-01'"),
        ("poll_runs", "UPDATE poll_runs SET status = 'invalid'"),
        ("poll_runs", "UPDATE poll_runs SET source_id = 999"),
        ("poll_runs", "UPDATE poll_runs SET post_count = -1"),
        ("poll_runs", "UPDATE poll_runs SET http_status = 999"),
        ("poll_runs", "UPDATE poll_runs SET completed_at = '2000-01-01'"),
        ("employers", "UPDATE employers SET name = ''"),
        ("employers", "DELETE FROM employers"),
        ("job_sources", "DELETE FROM job_sources"),
    ],
)
def test_database_constraints_even_with_raw_sql(session, table, sql):
    source = seed(session)
    session.add_all([posting(source.id), PollRun(source_id=source.id)])
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text(sql))
        session.commit()
    session.rollback()


def test_direct_duplicate_source_rejected(session):
    source = seed(session)
    session.commit()
    session.add(
        JobSource(
            employer_id=source.employer_id,
            provider=source.provider,
            board_identifier=source.board_identifier,
            careers_url=source.careers_url,
            api_endpoint=source.api_endpoint,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_posting_identity_is_per_source(session):
    first = seed(session)
    second = JobSource(
        employer_id=first.employer_id,
        provider="greenhouse",
        board_identifier="other",
        careers_url=first.careers_url,
        api_endpoint=first.api_endpoint,
    )
    session.add(second)
    session.flush()
    session.add_all([posting(first.id), posting(second.id)])
    session.commit()
    session.add(posting(first.id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_timestamps_convert_to_utc_and_publication_remains_unknown(session):
    source = seed(session)
    observed = datetime(2026, 10, 27, 10, tzinfo=timezone(timedelta(hours=-4)))
    entry = posting(source.id, first_seen_at=observed, last_seen_at=observed)
    session.add(entry)
    session.commit()
    session.expire_all()
    assert entry.first_seen_at == datetime(2026, 10, 27, 14, tzinfo=UTC)
    assert entry.first_seen_at.tzinfo == UTC
    assert entry.source_published_at is None
    assert entry.source_updated_at is None
    assert entry.date_provenance == "unknown"


def test_naive_timestamps_rejected(session):
    session.add(Employer(name="Example", created_at=datetime(2026, 1, 1)))
    with pytest.raises(StatementError, match="timezone"):
        session.flush()
    session.rollback()


def test_foreign_keys_on_every_connection(database):
    _, engine = database
    with engine.connect() as first, engine.connect() as second:
        assert first.scalar(text("PRAGMA foreign_keys")) == 1
        assert second.scalar(text("PRAGMA foreign_keys")) == 1
