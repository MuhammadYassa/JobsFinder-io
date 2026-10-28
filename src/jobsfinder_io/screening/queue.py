"""Durable screening work using existing workflow receipts, without network I/O."""

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, joinedload

from jobsfinder_io.persistence.models import JobSource, Posting, TaskRun, utc_now
from jobsfinder_io.relevance import assess_relevance
from jobsfinder_io.screening import pipelines_for


def queue_key(posting: dict) -> str:
    return (
        f"screen-queue:{posting['id']}:{posting['revision']}:{posting['content_hash']}"
    )


def refresh_queue(
    engine: Engine, *, posting_ids: list[int] | None = None
) -> list[dict]:
    """Queue active software/uncertain roles; supersede changed or inactive work.

    Baseline discoveries are eligible, but retain their baseline provenance.
    Caller may hold either monitoring or screening lock; SQLite serializes writes.
    """
    if posting_ids is not None and any(
        type(i) is not int or i <= 0 for i in posting_ids
    ):
        raise ValueError("posting_ids must contain positive integer IDs")
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.id == -1).values(status="pending")
        )
        query = select(Posting).options(
            joinedload(Posting.source).joinedload(JobSource.employer)
        )
        if posting_ids is not None:
            query = query.where(Posting.id.in_(posting_ids))
        jobs = []
        for post in session.scalars(query.order_by(Posting.first_seen_at, Posting.id)):
            if (
                post.status != "active"
                or assess_relevance(post.title, post.description_text) == "unrelated"
            ):
                continue
            jobs.append(
                {
                    "id": post.id,
                    "revision": post.revision,
                    "content_hash": post.content_hash,
                    "title": post.title,
                    "locations": post.locations,
                    "description": post.description_text,
                    "text": post.title
                    + "\n"
                    + post.locations
                    + "\n"
                    + post.description_text,
                    "url": post.canonical_job_url,
                    "application_url": post.apply_url,
                    "employer": post.source.employer.name,
                    "provider": post.source.provider,
                    "source_posting_id": post.external_posting_id,
                    "source_published_at": post.source_published_at.isoformat()
                    if post.source_published_at
                    else None,
                    "source_updated_at": post.source_updated_at.isoformat()
                    if post.source_updated_at
                    else None,
                    "first_seen_at": post.first_seen_at.isoformat(),
                    "date_provenance": post.date_provenance,
                    "discovery_kind": post.discovery_kind,
                    "pipelines": list(pipelines_for(post.locations)),
                }
            )
        current = {queue_key(job) for job in jobs}
        rows = list(
            session.scalars(
                select(TaskRun).where(TaskRun.task_key.startswith("screen-queue:"))
            )
        )
        existing = {row.task_key: row for row in rows}
        for row in rows:
            if (
                posting_ids is not None
                and row.payload.get("posting_id") not in posting_ids
            ):
                continue
            if row.task_key not in current:
                row.status = "superseded"
                row.completed_at = utc_now()
        for job in jobs:
            key = queue_key(job)
            if key not in existing:
                session.add(
                    TaskRun(
                        task_key=key,
                        status="pending",
                        payload={
                            "posting_id": job["id"],
                            "revision": job["revision"],
                            "content_hash": job["content_hash"],
                            "attempts": 0,
                        },
                    )
                )
            elif existing[key].status == "superseded":
                existing[key].status = "pending"
        return jobs


def mark_queue(engine: Engine, job: dict, status: str, **details) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(TaskRun).where(TaskRun.id == -1).values(status="pending")
        )
        row = session.scalar(select(TaskRun).where(TaskRun.task_key == queue_key(job)))
        if row is not None and row.status != "superseded":
            row.status = status
            row.payload = {**row.payload, **details}
            row.completed_at = utc_now() if status == "complete" else None
