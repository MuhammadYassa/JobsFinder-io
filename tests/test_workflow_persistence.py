"""Migration preservation and durable posting revision semantics."""

from datetime import UTC, datetime

from alembic import command
from conftest import migration_config
from sqlalchemy import text
from sqlalchemy.orm import Session

from jobsfinder_io.ingestion.polling import PollSummary, apply_snapshot
from jobsfinder_io.persistence.database import make_engine
from jobsfinder_io.persistence.models import JobSource, PollRun, Posting
from jobsfinder_io.registry import add_employer, add_source
from jobsfinder_io.sources.greenhouse import GreenhouseJob


def test_upgrade_preserves_populated_four_table_database(tmp_path):
    path = tmp_path / "upgrade.db"
    config = migration_config(path)
    command.upgrade(config, "e49ff864f16a")
    engine = make_engine(path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO employers (id,name,created_at,updated_at) VALUES (1,'Example',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO job_sources (id,employer_id,provider,board_identifier,careers_url,api_endpoint,created_at) VALUES (1,1,'greenhouse','example','https://example.com','https://example.com',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO postings (id,source_id,external_posting_id,title,canonical_job_url,apply_url,description_text,date_provenance,first_seen_at,last_seen_at,content_hash) VALUES (1,1,'a','Engineer','https://example.com/a','https://example.com/a','Python','unknown',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'hash')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO poll_runs (source_id,started_at,status) VALUES (1,CURRENT_TIMESTAMP,'failed')"
            )
        )
    engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(path)
    with Session(engine) as session:
        post = session.get(Posting, 1)
        assert post.title == "Engineer"
        assert post.last_changed_at == post.first_seen_at
        assert post.revision == 1 and post.discovery_kind == "baseline"
        assert session.get(JobSource, 1).provider == "greenhouse"
        assert session.get(PollRun, 1).status == "failed"
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
    engine.dispose()


def test_revision_only_changes_for_edits_and_reappearance(database):
    engine = database[1]
    job = GreenhouseJob(
        "a",
        None,
        "Engineer",
        "https://example.com/a",
        "https://example.com/a",
        "Python",
        None,
        "hash",
        locations="US",
    )
    with Session(engine) as session, session.begin():
        employer = add_employer(session, "Example")
        source = add_source(
            session, employer.id, "greenhouse", "example", "https://example.com"
        )
        source_id = source.id
        apply_snapshot(session, source_id, [job], PollSummary(1))
        now = datetime.now(UTC)
        session.add(
            PollRun(
                source_id=source_id,
                status="complete_success",
                started_at=now,
                completed_at=now,
            )
        )
    with Session(engine) as session, session.begin():
        post = session.get(Posting, 1)
        original = post.last_changed_at
        apply_snapshot(session, source_id, [job], PollSummary(2))
        assert post.revision == 1 and post.last_changed_at == original
        apply_snapshot(session, source_id, [], PollSummary(3))
        assert post.status == "missing_pending"
        apply_snapshot(session, source_id, [job], PollSummary(4))
        assert post.revision == 2 and post.locations == "US"
