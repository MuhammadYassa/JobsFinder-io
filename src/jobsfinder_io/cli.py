"""Registry, monitoring and cron-compatible personal workflows."""

import argparse
import json
import os
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
from jobsfinder_io.runlock import RunInProgress, database_run_lock


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
        "poll-source", help="Manually check a validated public ATS source"
    )
    poll.add_argument("--source-id", type=int, required=True)
    for name in ("poll-due", "health"):
        commands.add_parser(name)
    commands.add_parser(
        "test-email", help="Send one SMTP test to your configured personal recipient"
    )
    for name in ("discover", "screen", "screen-due", "report", "notify", "run-due"):
        command = commands.add_parser(name)
        if name in {"screen", "screen-due"}:
            command.add_argument(
                "--batch-size",
                type=int,
                help="Maximum jobs per request (1–25; token bounds can reduce it)",
            )
            command.add_argument(
                "--model", default=os.getenv("GEMINI_BATCH_MODEL") or None
            )
            command.add_argument(
                "--no-retries",
                action="store_true",
                help="Allow one attempt per Gemini request",
            )
            command.add_argument(
                "--posting-id",
                type=int,
                action="append",
                dest="posting_ids",
                help="Screen only this stored posting; repeat to select a small batch",
            )
        if name in {"discover", "run-due"}:
            command.add_argument(
                "--candidates",
                type=Path,
                default=os.getenv("JOBSFINDER_CANDIDATES") or None,
            )
        if name in {"screen", "screen-due", "report", "notify", "run-due"}:
            command.add_argument(
                "--profile", type=Path, default=os.getenv("JOBSFINDER_PROFILE") or None
            )
        if name in {"report", "notify", "run-due"}:
            command.add_argument(
                "--local-only",
                action="store_true",
                help="Write local artifacts without queuing or sending email",
            )
            command.add_argument(
                "--output-dir",
                type=Path,
                default=os.getenv("JOBSFINDER_REPORT_DIR") or "data/reports",
            )
        if name in {"screen", "screen-due", "run-due"}:
            command.add_argument(
                "--preliminary-model",
                default=os.getenv("GEMINI_PRELIMINARY_MODEL")
                or "gemini-3.5-flash-lite",
            )
            command.add_argument(
                "--review-model",
                default=os.getenv("GEMINI_REVIEW_MODEL") or "gemini-3.5-flash-lite",
            )
            command.add_argument(
                "--max-calls", type=int, default=os.getenv("GEMINI_MAX_CALLS") or 0
            )
    return parser


def run_workflow(args: argparse.Namespace, engine) -> dict:
    """Operational commands share one process lock; secrets never enter argv."""
    from jobsfinder_io.delivery import (
        deliver_pending,
        load_smtp_config,
        send_test_email,
    )
    from jobsfinder_io.discovery import discover
    from jobsfinder_io.operations import health, poll_due, run_due
    from jobsfinder_io.reporting.non_ai import generate_reports, notify_jobs

    if args.command == "health":
        return health(engine)
    if args.command == "poll-due":
        return poll_due(engine)
    if args.command == "test-email":
        return send_test_email(engine, load_smtp_config())
    if args.command == "discover":
        if args.candidates is None:
            raise ValueError("Set --candidates or JOBSFINDER_CANDIDATES")
        return discover(engine, args.candidates)
    if args.command in {"report", "notify"}:
        action = generate_reports if args.command == "report" else notify_jobs
        result = action(engine, args.output_dir, enqueue=not args.local_only)
        if not args.local_only:
            result["email"] = deliver_pending(engine, load_smtp_config())
        return result
    if args.command in {"screen", "screen-due"}:
        from jobsfinder_io.screening import screen_jobs
        from jobsfinder_io.screening.batch_limits import load_batch_config

        extra = {}
        if args.batch_size is not None:
            from dataclasses import replace

            extra["batch_config"] = replace(
                load_batch_config(), max_jobs=args.batch_size
            )
        if args.command == "screen-due":
            from jobsfinder_io.screening.sessions import screen_due

            return screen_due(
                engine,
                args.profile,
                enabled=os.getenv("GEMINI_BATCH_ENABLED", "false").lower() == "true",
                api_key=os.getenv("GEMINI_API_KEY"),
                model=args.model or args.review_model,
                max_calls=args.max_calls,
                config=extra.get("batch_config") or load_batch_config(),
                max_attempts=1 if args.no_retries else 2,
                **(
                    {"posting_ids": args.posting_ids}
                    if args.posting_ids is not None
                    else {}
                ),
            )

        return screen_jobs(
            engine,
            args.profile,
            api_key=os.getenv("GEMINI_API_KEY"),
            preliminary_model=args.preliminary_model,
            review_model=args.model or args.review_model,
            max_calls=args.max_calls,
            **(
                {"posting_ids": args.posting_ids}
                if args.posting_ids is not None
                else {}
            ),
            **({"max_attempts": 1} if args.no_retries else {}),
            **extra,
        )
    return run_due(
        engine,
        profile_path=args.profile,
        candidates_path=args.candidates,
        output_dir=args.output_dir,
        local_only=args.local_only,
    )


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
        lock_path = (
            args.db.with_name(args.db.stem + ".screening.db")
            if args.command in {"screen", "screen-due"}
            else args.db
        )
        with database_run_lock(lock_path):
            return _execute(args, engine)
    except (RegistryError, ValueError, OSError, RunInProgress) as exc:
        # File/JSON errors can contain paths but must never echo file contents.
        message = (
            str(exc)
            if isinstance(exc, (RegistryError, RunInProgress))
            else type(exc).__name__
        )
        print(f"Error: {message}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Database operation failed; run Alembic upgrade head and check permissions.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


def _execute(args: argparse.Namespace, engine) -> int:
    try:
        if args.command in {
            "poll-due",
            "health",
            "discover",
            "screen",
            "screen-due",
            "report",
            "notify",
            "run-due",
            "test-email",
        }:
            result = run_workflow(args, engine)
            print(json.dumps(result, default=str, sort_keys=True))
            if args.command == "test-email":
                return 0 if result.get("status") == "sent" else 1

            # Aggregate commands retain partial results and make failures visible
            # to cron through a nonzero exit code.
            def failed(value):
                if not isinstance(value, dict):
                    return False
                return bool(
                    value.get("error")
                    or value.get("failed")
                    or value.get("uncertain")
                    or value.get("status") == "failed"
                ) or any(failed(item) for item in value.values())

            return 1 if args.command != "health" and failed(result) else 0
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
    return 0
