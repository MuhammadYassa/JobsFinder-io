"""Local and queued email reports with no model, profile, or eligibility dependency."""

import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, func, or_, select
from sqlalchemy.orm import Session, joinedload

from jobsfinder_io.persistence.models import (
    Delivery,
    Employer,
    JobSource,
    PollRun,
    Posting,
    TaskRun,
    utc_now,
)
from jobsfinder_io.relevance import (
    assess_relevance,
    location_group,
    requirement_excerpts,
)


def enqueue_email(*args, **kwargs):
    # Keep SMTP setup optional for local-only operations.
    from jobsfinder_io.delivery import enqueue_email as enqueue

    return enqueue(*args, **kwargs)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _identity(post: Posting) -> tuple:
    # No fuzzy employer/title matching: distinct jobs must survive deduplication.
    return post.source.employer_id, post.apply_url, post.content_hash


def _select(session: Session, posts: list[Posting], channel: str) -> list[Posting]:
    receipts = session.execute(
        select(Delivery, Posting)
        .join(Posting, Delivery.posting_id == Posting.id)
        .where(Delivery.channel == channel)
        .where(Delivery.status != "superseded")
        .options(joinedload(Posting.source))
    ).all()
    delivered = {(receipt.posting_id, receipt.revision) for receipt, _ in receipts}
    # Old revision receipts must never suppress a changed posting.
    seen = {
        _identity(post)
        for receipt, post in receipts
        if receipt.revision == post.revision
    }
    result = []
    for post in posts:
        key = _identity(post)
        if (post.id, post.revision) not in delivered and key not in seen:
            result.append(post)
            seen.add(key)
    return result


def _items(posts: list[Posting], channel: str) -> list[dict]:
    return [
        {
            "posting_id": p.id,
            "revision": p.revision,
            "pipeline": location_group(p.locations)[0],
            "channel": channel,
        }
        for p in posts
    ]


def _entry(post: Posting) -> str:
    _, country = location_group(post.locations)
    published = (
        f"Source publication: {post.source_published_at.isoformat()} "
        f"(source evidence: {post.date_provenance}; independently unverified)"
        if post.source_published_at
        else "Publication date unknown; freshness uncertain"
    )
    baseline = (
        "Initial baseline (not newly published)"
        if (post.discovery_kind == "baseline" and post.revision == 1)
        else "New discovery"
        if post.revision == 1
        else "Materially changed/reappeared"
    )
    excerpts = "\n".join(
        f"  Source excerpt: {s}" for s in requirement_excerpts(post.description_text)
    )
    return (
        f"- {post.title} — {post.source.employer.name}\n"
        f"  Location: {post.locations or 'Unknown'}; {country}\n"
        f"  {baseline}; first seen: {post.first_seen_at.isoformat()}\n"
        f"  {published}\n"
        f"  Source updated: {post.source_updated_at.isoformat() if post.source_updated_at else 'Unknown'}; "
        f"last verified: {post.last_seen_at.isoformat()}\n"
        f"  Relevance: {assess_relevance(post.title, post.description_text)}; "
        "eligibility/sponsorship/start date unverified\n"
        f"  Apply: {post.apply_url}\n{excerpts}\n"
    )


def _body(posts: list[Posting], now: datetime, metrics: dict, *, alert: bool) -> str:
    lines = [
        "JobsFinder.io — " + ("new job alerts" if alert else "seven-day job report"),
        f"Generated: {now.isoformat()}",
        "Deterministic relevance only. No AI eligibility assessment or ranking.",
        "Counts since previous report: "
        + "; ".join(f"{k}: {v}" for k, v in metrics.items()),
        f"Included unique postings: {len(posts)}",
        "",
    ]
    for group, label in (
        ("us", "US"),
        ("international", "International"),
        ("unknown", "Country unknown or multiple countries — review"),
    ):
        lines.append(f"## {label}")
        grouped = [post for post in posts if location_group(post.locations)[0] == group]
        for baseline, heading in (
            (False, "New discoveries / material changes"),
            (True, "Initial baseline — not newly published"),
        ):
            selected = [
                p
                for p in grouped
                if (p.discovery_kind == "baseline" and p.revision == 1) == baseline
            ]
            lines.append(f"### {heading} ({len(selected)})")
            lines.extend(_entry(post) for post in selected)
    return "\n".join(lines) + "\n"


def _metrics(session: Session, since: datetime, now: datetime) -> dict:
    def count(model, *conditions):
        return (
            session.scalar(select(func.count()).select_from(model).where(*conditions))
            or 0
        )

    window = (PollRun.started_at > since, PollRun.started_at <= now)
    return {
        "sources_checked": session.scalar(
            select(func.count(func.distinct(PollRun.source_id))).where(*window)
        )
        or 0,
        "successful_checks": count(
            PollRun, *window, PollRun.status == "complete_success"
        ),
        "failed_or_partial_checks": count(
            PollRun, *window, PollRun.status.in_(["failed", "partial"])
        ),
        "new_employers": count(
            Employer, Employer.created_at > since, Employer.created_at <= now
        ),
        "new_postings": count(
            Posting,
            Posting.first_seen_at > since,
            Posting.first_seen_at <= now,
            Posting.discovery_kind == "new",
        ),
        "baseline_postings": count(
            Posting,
            Posting.first_seen_at > since,
            Posting.first_seen_at <= now,
            Posting.discovery_kind == "baseline",
        ),
    }


def _run(engine: Engine, output_dir, *, now, slot_key, enqueue, alert) -> dict:
    now = now or utc_now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    prefix = "nonai-alert" if alert else "nonai-report"
    local_channel = "local_nonai_alert" if alert else "local_nonai_report"
    smtp_channel = "smtp_alert" if alert else "smtp_report"
    with Session(engine) as session:
        # Include lifecycle changes even for no-longer-eligible jobs. Otherwise
        # A/B -> A/B/C -> A/B reuses an archived key and can retain stale C mail.
        alert_state = (
            list(
                session.execute(
                    select(Posting.id, Posting.revision, Posting.status).order_by(
                        Posting.id
                    )
                )
            )
            if alert
            else []
        )
        posts = list(
            session.scalars(
                select(Posting)
                .where(
                    Posting.status == "active",
                    Posting.first_seen_at <= now,
                    Posting.last_changed_at <= now,
                    or_(
                        Posting.first_seen_at >= now - timedelta(days=7),
                        Posting.last_changed_at >= now - timedelta(days=7),
                    ),
                )
                .options(joinedload(Posting.source).joinedload(JobSource.employer))
                .order_by(Posting.first_seen_at.desc(), Posting.id)
            )
        )
        posts = [
            post
            for post in posts
            if assess_relevance(post.title, post.description_text) != "unrelated"
        ]
        if alert:
            posts = [
                post
                for post in posts
                if post.discovery_kind != "baseline" or post.revision > 1
            ]
    token = slot_key or (
        hashlib.sha256(
            repr(([(p.id, p.revision) for p in posts], alert_state)).encode()
        ).hexdigest()[:20]
        if alert
        else now.isoformat()
    )
    key = f"{prefix}:{token}"
    with Session(engine) as session:
        existing_snapshot = session.scalar(
            select(TaskRun.id).where(TaskRun.task_key == key)
        )
    if enqueue and existing_snapshot is None:
        from jobsfinder_io.delivery import supersede_unsent_reports

        if not alert:
            supersede_unsent_reports(engine, key)
        else:
            from jobsfinder_io.delivery import supersede_unsent_alerts

            supersede_unsent_alerts(engine, key)
    with Session(engine) as session:
        local_posts = _select(session, posts, local_channel)
        email_posts = _select(session, posts, smtp_channel)
        if alert and not local_posts and not email_posts:
            return {"path": None, "count": 0, "email": {"status": "nothing_new"}}
        old = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
        if (
            old
            and old.status == "complete"
            and (not enqueue or old.payload.get("email"))
        ):
            return {
                **{k: v for k, v in old.payload.items() if not k.startswith("_")},
                "duplicate": True,
            }
        previous = session.scalar(
            select(TaskRun)
            .where(
                TaskRun.task_key.like("nonai-report:%"),
                TaskRun.status == "complete",
                TaskRun.started_at < now,
            )
            .order_by(TaskRun.started_at.desc())
            .limit(1)
        )
        since = previous.started_at if previous else now - timedelta(days=7)
        metrics = _metrics(session, since, now)
        local_body = _body(local_posts, now, metrics, alert=alert)
        email_body = _body(email_posts, now, metrics, alert=alert)
        items = _items(email_posts, smtp_channel)
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        path = Path(output_dir) / f"{prefix}-{digest}.md"
        email_path = Path(output_dir) / f"{prefix}-{digest}-email.md"
        result = {
            "path": str(path),
            "count": len(local_posts),
            "email_count": len(email_posts),
            "metrics": metrics,
            "slot_key": token,
        }
        if old and old.payload.get("_email_body"):
            # Resume the exact message after a crash; local receipts already exist.
            saved = old.payload
            result = {k: v for k, v in saved.items() if not k.startswith("_")}
            result.pop("email", None)
            email_body, items = saved["_email_body"], saved["_items"]
            path = Path(result["path"])
            email_path = Path(saved["_email_path"])
            local_posts = []
        else:
            if old and path.exists():
                result["count"] = old.payload.get("count", result["count"])
                local_posts = []
            else:
                _write(path, local_body)
            _write(email_path, email_body)
        for item in _items(local_posts, local_channel):
            session.add(
                Delivery(**item, status="sent", artifact_path=str(path), sent_at=now)
            )
        if old is None:
            old = TaskRun(task_key=key, started_at=now, status="complete")
            session.add(old)
        old.status = "pending" if enqueue else "complete"
        old.completed_at = None if enqueue else now
        snapshot = {
            "_email_body": email_body,
            "_items": items,
            "_email_path": str(email_path),
        }
        old.payload = {**result, **snapshot}
        session.commit()
    if enqueue and (not alert or items):
        result["email"] = enqueue_email(
            engine,
            key,
            "JobsFinder.io — "
            + (
                "new software job alerts"
                if alert
                else "US and international job report"
            ),
            email_body,
            items=items,
            artifact_path=str(email_path),
        )
        with Session(engine) as session, session.begin():
            task = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
            task.payload = {**result, **snapshot}
            accepted = result["email"].get("status") not in {"conflict", "error"}
            task.status = "complete" if accepted else "pending"
            task.completed_at = now if accepted else None
            if not accepted:
                # Another group reserved some items: rebuild from fresh receipts.
                task.payload = result
        if not accepted:
            raise RuntimeError("Email group reservation conflict; retry report")
    return result


def generate_reports(
    engine: Engine, output_dir, *, now=None, slot_key=None, enqueue=True
) -> dict:
    return _run(
        engine, output_dir, now=now, slot_key=slot_key, enqueue=enqueue, alert=False
    )


def notify_jobs(engine: Engine, output_dir, *, now=None, enqueue=True) -> dict:
    return _run(engine, output_dir, now=now, slot_key=None, enqueue=enqueue, alert=True)
