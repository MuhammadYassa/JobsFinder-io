"""One manual source check: durable attempt, HTTP, then atomic reconciliation."""

from dataclasses import dataclass, replace

import httpx
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import JobSource, PollRun, Posting, utc_now
from jobsfinder_io.registry import RegistryError
from jobsfinder_io.sources.adapters import make_collector
from jobsfinder_io.sources.greenhouse import (
    CollectorError,
    GreenhouseCollector,
    GreenhouseJob,
)


@dataclass
class PollSummary:
    run_id: int
    status: str = "running"
    observed: int = 0
    baseline: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    closed: int = 0
    reappeared: int = 0
    enrichment_failed: int = 0
    error_code: str | None = None


def poll_source(
    engine: Engine,
    source_id: int,
    *,
    collector: GreenhouseCollector | None = None,
    detail_budget: int = 100,
) -> PollSummary:
    """Own short transactions; no database lock is held during HTTP requests.

    A running row prevents overlapping checks of the same source. Hard process
    termination leaves that row visible for manual investigation rather than
    pretending that an incomplete scan succeeded.
    """
    if detail_budget < 0:
        raise ValueError("Detail budget cannot be negative")
    if collector is None:
        # No environment proxies, ambient credentials, or redirect following.
        with httpx.Client(trust_env=False) as client:
            with Session(engine) as session:
                source = session.get(JobSource, source_id)
                if source is None:
                    raise RegistryError(f"Source {source_id} does not exist")
                provider = source.provider
            return poll_source(
                engine,
                source_id,
                collector=make_collector(provider, client),
                detail_budget=detail_budget,
            )

    with Session(engine) as session, session.begin():
        started = utc_now()
        # The first statement obtains SQLite's writer lock, serializing the
        # running-row check and insertion across independent CLI processes.
        result = session.execute(
            update(JobSource)
            .where(JobSource.id == source_id)
            .values(last_attempt_at=started)
        )
        if result.rowcount != 1:
            raise RegistryError(f"Source {source_id} does not exist")
        source = session.get(JobSource, source_id)
        running = session.scalar(
            select(PollRun.id)
            .where(PollRun.source_id == source_id, PollRun.status == "running")
            .limit(1)
        )
        run = PollRun(source_id=source_id, started_at=started)
        session.add(run)
        session.flush()
        summary = PollSummary(run_id=run.id)
        if running is not None:
            _finish_failure(
                session,
                run,
                source,
                summary,
                CollectorError("poll_in_progress"),
                count_failure=False,
            )
            return summary
        if (
            source.provider not in {"greenhouse", "lever", "lever_eu", "ashby"}
            or source.validated_at is None
            or source.status not in {"validated", "error"}
        ):
            _finish_failure(
                session, run, source, summary, CollectorError("source_not_pollable")
            )
            return summary
        token = source.board_identifier
        provider = source.provider
        existing = list(
            session.scalars(select(Posting).where(Posting.source_id == source_id))
        )
        needs_publication = {
            post.external_posting_id
            for post in existing
            if post.source_published_at is None
            and post.date_provenance != "unknown:greenhouse.first_published_absent"
        }
        known_ids = {post.external_posting_id for post in existing}

    try:
        jobs = collector.fetch_jobs(token)
        # Keep list HTTP status independent of optional detail requests.
        if provider == "greenhouse":
            jobs = _enrich_jobs(
                collector,
                token,
                jobs,
                known_ids,
                needs_publication,
                summary,
                detail_budget,
            )
        with Session(engine) as session, session.begin():
            run = session.get(PollRun, summary.run_id)
            source = session.get(JobSource, source_id)
            apply_snapshot(session, source_id, jobs, summary)
            completed = utc_now()
            run.status = summary.status = "complete_success"
            run.completed_at = source.last_success_at = completed
            run.http_status = 200
            run.post_count = summary.observed = len(jobs)
            run.error_code = summary.error_code
            source.consecutive_failures = 0
    except CollectorError as exc:
        with Session(engine) as session, session.begin():
            _finish_failure(
                session,
                session.get(PollRun, summary.run_id),
                session.get(JobSource, source_id),
                summary,
                exc,
            )
    except SQLAlchemyError:
        # Snapshot writes rolled back. Preserve a separate failure record if
        # SQLite is still writable, without keeping any partial job changes.
        with Session(engine) as session, session.begin():
            summary = PollSummary(summary.run_id)
            _finish_failure(
                session,
                session.get(PollRun, summary.run_id),
                session.get(JobSource, source_id),
                summary,
                CollectorError("persistence_error", http_status=200),
            )
    except BaseException:
        # Interruptions/unexpected bugs are not successful polls either. Keep
        # the original exception visible after best-effort bookkeeping.
        try:
            with Session(engine) as session, session.begin():
                _finish_failure(
                    session,
                    session.get(PollRun, summary.run_id),
                    session.get(JobSource, source_id),
                    summary,
                    CollectorError("interrupted"),
                )
        except SQLAlchemyError:
            pass  # A durable running record remains if storage is unavailable.
        raise
    return summary


def _enrich_jobs(
    collector: GreenhouseCollector,
    token: str,
    jobs: list[GreenhouseJob],
    known_ids: set[str],
    needs_publication: set[str],
    summary: PollSummary,
    budget: int,
) -> list[GreenhouseJob]:
    enriched = []
    rate_limited = False
    for job in jobs:
        if (
            job.external_posting_id in known_ids
            and job.external_posting_id not in needs_publication
        ):
            enriched.append(job)
            continue
        try:
            if rate_limited:
                raise CollectorError("detail_rate_limited")
            if budget == 0:
                raise CollectorError("detail_budget_exhausted")
            budget -= 1
            job = collector.enrich_publication(token, job)
        except CollectorError as exc:
            if exc.http_status == 429:
                rate_limited = True
            summary.enrichment_failed += 1
            job = replace(
                job, date_provenance=f"unknown:greenhouse.detail_error:{exc.code}"
            )
        enriched.append(job)
    if summary.enrichment_failed:
        summary.error_code = (
            f"publication_enrichment_failed:{summary.enrichment_failed}"
        )
    return enriched


def apply_snapshot(
    session: Session, source_id: int, jobs: list[GreenhouseJob], summary: PollSummary
) -> None:
    """Reconcile a complete validated list. Caller commits jobs and poll together."""
    previous_success = session.scalar(
        select(PollRun.id)
        .where(PollRun.source_id == source_id, PollRun.status == "complete_success")
        .limit(1)
    )
    baseline = previous_success is None
    existing = {
        post.external_posting_id: post
        for post in session.scalars(
            select(Posting).where(Posting.source_id == source_id)
        )
    }
    observed_at = utc_now()
    observed_ids = set()
    for job in jobs:
        identity = job.external_posting_id
        observed_ids.add(identity)
        post = existing.get(identity)
        if post is None:
            post = Posting(
                source_id=source_id,
                external_posting_id=identity,
                first_seen_at=observed_at,
                last_changed_at=observed_at,
                discovery_kind="baseline" if baseline else "new",
                revision=1,
                date_provenance=job.date_provenance,
            )
            session.add(post)
            if baseline:
                summary.baseline += 1
            else:
                summary.new += 1
        elif post.status in {"missing_pending", "closed"}:
            post.revision += 1
            post.last_changed_at = observed_at
            summary.reappeared += 1
            # Reappearance and content edits may both be useful information.
            if post.content_hash != job.content_hash:
                summary.updated += 1
        elif post.content_hash != job.content_hash:
            post.revision += 1
            post.last_changed_at = observed_at
            summary.updated += 1
        else:
            summary.unchanged += 1
        post.external_requisition_id = job.external_requisition_id
        post.title = job.title
        post.canonical_job_url = job.canonical_job_url
        post.apply_url = job.apply_url
        post.description_text = job.description_text
        post.locations = job.locations
        post.source_updated_at = job.source_updated_at
        post.content_hash = job.content_hash
        post.last_seen_at = max(observed_at, post.first_seen_at)
        post.status = "active"
        # A list never supplies publication evidence. Preserve earlier detail
        # evidence when no enrichment was needed or a later detail request fails.
        if (
            job.source_published_at is not None or post.source_published_at is None
        ) and job.date_provenance != "unknown:greenhouse.first_published_not_checked":
            post.source_published_at = job.source_published_at
            post.date_provenance = job.date_provenance
    if not baseline:
        for identity, post in existing.items():
            if identity not in observed_ids:
                if post.status == "missing_pending":
                    post.status = "closed"
                    summary.closed += 1
                elif post.status != "closed":
                    post.status = "missing_pending"
                    summary.missing += 1
    session.flush()


def _finish_failure(
    session: Session,
    run: PollRun,
    source: JobSource,
    summary: PollSummary,
    error: CollectorError,
    *,
    count_failure: bool = True,
) -> None:
    run.status = summary.status = error.status
    run.completed_at = utc_now()
    run.http_status = error.http_status
    run.post_count = error.post_count
    run.error_code = summary.error_code = error.code
    summary.observed = error.post_count or 0
    if count_failure:
        source.consecutive_failures += 1
    session.flush()
