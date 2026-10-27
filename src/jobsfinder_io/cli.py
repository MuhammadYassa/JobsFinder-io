"""Registry commands and manual public Greenhouse checks."""

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from jobsfinder_io.ingestion.polling import poll_source
from jobsfinder_io.persistence.database import make_engine
from jobsfinder_io.registry import (
    RegistryError,
    add_employer,
    add_source,
    list_postings,
    list_sources,
    validate_source,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JobsFinder.io local registry")
    parser.add_argument("--db", type=Path, default=Path("data/jobsfinder.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    employer = commands.add_parser("add-employer")
    employer.add_argument("--name", required=True)
    employer.add_argument("--official-domain")
    source = commands.add_parser("add-source")
    source.add_argument("--employer-id", type=int, required=True)
    source.add_argument("--provider", required=True)
    source.add_argument("--board-identifier", required=True)
    source.add_argument("--careers-url", required=True)
    source.add_argument("--poll-interval-minutes", type=int, default=60)
    commands.add_parser("list-sources")
    validation = commands.add_parser("validate-source")
    validation.add_argument("source_id", type=int)
    validation.add_argument("--confirm-official-association", action="store_true")
    validation.add_argument("--confirm-public-access", action="store_true")
    postings = commands.add_parser("list-postings")
    postings.add_argument("--source-id", type=int)
    poll = commands.add_parser(
        "poll-source", help="Manually check a validated Greenhouse source"
    )
    poll.add_argument("--source-id", type=int, required=True)
    return parser


def run(args: argparse.Namespace, session: Session) -> None:
    if args.command == "add-employer":
        employer = add_employer(session, args.name, args.official_domain)
        print(f"Employer {employer.id}: {employer.name}")
    elif args.command == "add-source":
        source = add_source(
            session,
            args.employer_id,
            args.provider,
            args.board_identifier,
            args.careers_url,
            args.poll_interval_minutes,
        )
        print(
            f"Source {source.id}: {source.provider}/{source.board_identifier} (candidate)"
        )
    elif args.command == "list-sources":
        for source in list_sources(session):
            print(
                f"{source.id}\t{source.employer_id}\t{source.employer.name}\t"
                f"{source.provider}\t{source.board_identifier}\t{source.status}"
            )
    elif args.command == "validate-source":
        source = validate_source(
            session,
            args.source_id,
            official_association_confirmed=args.confirm_official_association,
            public_access_confirmed=args.confirm_public_access,
        )
        print(f"Source {source.id}: validated (manual confirmation)")
    elif args.command == "list-postings":
        for posting in list_postings(session, args.source_id):
            print(
                f"{posting.id}\t{posting.source_id}\t{posting.external_posting_id}\t"
                f"{posting.title}\t{posting.status}\t{posting.canonical_job_url}"
            )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.db.is_file():
        print(
            "Database not found. Run Alembic upgrade head first (see README).",
            file=sys.stderr,
        )
        return 1
    engine = make_engine(args.db)
    try:
        if args.command == "poll-source":
            summary = poll_source(engine, args.source_id)
            print(
                f"{summary.status} | poll={summary.run_id} | observed={summary.observed} | "
                f"baseline={summary.baseline} | new={summary.new} | updated={summary.updated} | "
                f"unchanged={summary.unchanged} | missing={summary.missing} | "
                f"closed={summary.closed} | reappeared={summary.reappeared} | "
                f"enrichment_failed={summary.enrichment_failed}"
                + (f" | {summary.error_code}" if summary.error_code else "")
            )
            return 0 if summary.status == "complete_success" else 1
        with Session(engine) as session, session.begin():
            run(args, session)
    except RegistryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Database operation failed; changes rolled back. Check file permissions "
            "and run Alembic upgrade head (see README).",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()
    return 0
