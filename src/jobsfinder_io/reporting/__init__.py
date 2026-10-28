"""Private local reports, factual letter drafts, and optional Telegram alerts.

Telegram sendMessage reference: https://core.telegram.org/bots/api#sendmessage
Timeouts after a POST are ambiguous: preserve an uncertain receipt, never replay
automatically. Local artifacts remain available for manual recovery.
"""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session, joinedload

from jobsfinder_io.persistence.models import (
    Delivery,
    JobSource,
    Posting,
    ScreeningResult,
    utc_now,
)
from jobsfinder_io.screening import load_profile, pipelines_for, profile_fingerprint

PRIORITY_COUNTRIES = {
    "germany",
    "ireland",
    "uk",
    "united kingdom",
    "uae",
    "united arab emirates",
    "canada",
    "singapore",
}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical(url: str) -> str:
    parsed = urlsplit(url)
    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"gh_src", "lever-source"}
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            urlencode(params),
            ""
            if parsed.fragment in {"", "apply"} or parsed.fragment.startswith("utm_")
            else parsed.fragment,
        )
    )


def _keys(post: Posting) -> set[tuple[int, str]]:
    return {
        (post.source.employer_id, _canonical(link))
        for link in (post.canonical_job_url, post.apply_url)
        if link
    }


def _current_results(
    session: Session, posts: list[Posting], fingerprint: str | None = None
) -> dict:
    identities = {p.id: p.content_hash for p in posts}
    if not identities:
        return {}
    results = {}
    versions = {}
    priorities = {"final": 5, "review": 4, "preliminary": 2, "fallback": 1}
    for result in session.scalars(
        select(ScreeningResult)
        .where(ScreeningResult.posting_id.in_(identities))
        .order_by(ScreeningResult.id.desc())
    ):
        if identities.get(result.posting_id) != result.content_hash:
            continue
        if fingerprint is not None and result.profile_hash != fingerprint:
            continue
        key = (result.posting_id, result.pipeline)
        version = (result.profile_hash, result.policy_version, result.prompt_version)
        versions.setdefault(key, version)
        if versions[key] != version:
            continue
        existing = results.get(key)
        if existing is None or priorities.get(result.stage, 0) > priorities.get(
            existing.stage, 0
        ):
            results[key] = result
    return results


def _disposition(result: ScreeningResult | None) -> str:
    if result is None or result.stage in {"preliminary", "fallback"}:
        return "needs_review"
    return result.disposition


def _recent_posts(session: Session, now: datetime) -> list[Posting]:
    cutoff = now - timedelta(days=7)
    return list(
        session.scalars(
            select(Posting)
            .options(joinedload(Posting.source).joinedload(JobSource.employer))
            .where(
                Posting.status == "active",
                or_(Posting.first_seen_at >= cutoff, Posting.last_changed_at >= cutoff),
            )
            .order_by(Posting.id)
        )
    )


def _freshness(post: Posting, now: datetime) -> str:
    if post.discovery_kind == "baseline":
        return "baseline discovery; original freshness uncertain"
    if (
        post.source_published_at is not None
        and now - timedelta(days=7) <= post.source_published_at <= now
    ):
        return "verified-new: source publication evidence within seven days"
    return "freshness uncertain: newly observed does not mean newly published"


def _entry(post: Posting, result: ScreeningResult | None, now: datetime) -> str:
    payload = result.payload if result else {}
    lines = [
        f"### {post.title} — {post.source.employer.name}",
        "",
        f"Official application: {post.apply_url}",
        f"Locations: {post.locations or 'unknown'}",
        f"Disposition: {_disposition(result)}; score: {result.score if result else 0}",
        f"Freshness: {_freshness(post, now)}",
        f"Source publication: {post.source_published_at.isoformat() if post.source_published_at else 'unknown'}",
        f"Source update: {post.source_updated_at.isoformat() if post.source_updated_at else 'unknown'}",
        f"First discovered: {post.first_seen_at.isoformat()}; last verified: {post.last_seen_at.isoformat()}",
        f"Material change: {post.last_changed_at.isoformat()}; revision: {post.revision}",
        f"Date evidence: {post.date_provenance}",
        f"Fit: {payload.get('primary_reason', 'Awaiting screening; eligibility unknown')}",
        f"Immigration class: {payload.get('visa_class', 'B')}; start-date class: {payload.get('start_class', 'B')}",
        f"Required experience: {payload.get('required_experience') or 'unknown'}; preferred: {payload.get('preferred_experience') or 'unknown'}",
    ]
    for concern in payload.get("uncertainty", []):
        lines.append(f"Concern: {concern}")
    for evidence in payload.get("evidence", []):
        lines.extend(
            [f"> {evidence['quote']}", f"Evidence source: {evidence['source_url']}"]
        )
    if result:
        lines.append(
            f"Review provenance: {result.model}; {result.prompt_version}; {result.policy_version}"
        )
    return "\n".join(lines) + "\n"


def cover_letter(post: Posting, profile: dict) -> str:
    """Use exact private facts, never generated achievements or employer claims."""
    facts = profile.get("cover_letter_facts") or profile.get("facts", [])
    usable = [
        fact.strip() for fact in facts if fact.strip() and len(fact.split()) <= 30
    ]
    detail = usable[0] if usable else ""
    skills = [
        skill for skill in profile.get("skills", []) if 0 < len(skill.split()) <= 3
    ][:5]
    skill_sentence = f"My listed skills include {', '.join(skills)}." if skills else ""
    title = " ".join(post.title.split()[:10])
    employer = " ".join(post.source.employer.name.split()[:8])
    text = (
        f"Dear Hiring Team,\n\nI am applying for the {title} position at {employer}. "
        "I would welcome the opportunity to discuss the role and explain how my background "
        "could contribute to your team. "
        f"{detail} {skill_sentence} "
        "I am interested in understanding the problems this position addresses, the team's "
        "priorities, and the expectations for someone joining the organization. I would "
        "appreciate a conversation about the responsibilities described in the posting "
        "and the qualifications you consider most important. Please consider this letter "
        "alongside my resume and project materials. I would be glad to provide further "
        "details about the experience stated in those materials and answer any questions. "
        "Thank you for your time and consideration.\n\nSincerely,\nThe applicant"
    )
    if len(text.split()) > 160:
        return cover_letter(post, {"skills": skills})
    return text


def generate_reports(
    engine: Engine,
    output_dir: str | Path,
    *,
    profile_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Report time must include timezone")
    profile = load_profile(profile_path) if profile_path else None
    fingerprint = profile_fingerprint(profile) if profile is not None else None
    priority_countries = {
        str(country).lower()
        for country in (profile or {})
        .get("international", {})
        .get("priority_countries", PRIORITY_COUNTRIES)
    }
    directory = Path(output_dir)
    summary = {"paths": [], "letters": 0, "pipelines": {}}
    with Session(engine) as session, session.begin():
        # Serialize direct CLI calls as well as scheduler invocations on SQLite.
        session.execute(
            update(Delivery).where(Delivery.id == -1).values(status="pending")
        )
        posts = _recent_posts(session, now)
        results = _current_results(session, posts, fingerprint)
        stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        for pipeline in ("us", "international"):
            pipeline_posts = [
                post for post in posts if pipeline in pipelines_for(post.locations)
            ]
            previous = list(
                session.scalars(
                    select(Delivery).where(
                        Delivery.pipeline == pipeline,
                        Delivery.channel == "local_report",
                        Delivery.status == "sent",
                    )
                )
            )
            delivered = {(d.posting_id, d.revision) for d in previous}
            delivered_keys = set()
            for delivery in previous:
                post = session.get(Posting, delivery.posting_id)
                if post is not None and post.revision == delivery.revision:
                    delivered_keys.update(_keys(post))
            ranked = []
            review = []
            rejected = 0
            already_reported = 0
            duplicate = 0
            for post in pipeline_posts:
                result = results.get((post.id, pipeline))
                if _disposition(result) == "needs_review":
                    review.append((post, result))
                elif result.disposition == "reject":
                    rejected += 1
                elif result.disposition in {"recommend", "stretch"}:
                    if (post.id, post.revision) in delivered:
                        already_reported += 1
                    else:
                        ranked.append((post, result))
            ranked.sort(
                key=lambda item: (
                    item[1].disposition == "stretch",
                    pipeline == "international"
                    and str(item[1].payload.get("country", "")).lower()
                    not in priority_countries,
                    -item[1].score,
                    -item[0].last_changed_at.timestamp(),
                    item[0].id,
                )
            )
            selected = []
            for post, result in ranked:
                keys = _keys(post)
                if keys & delivered_keys:
                    duplicate += 1
                    continue
                delivered_keys.update(keys)
                selected.append((post, result))
            counts = {
                "stored_active_in_window": len(pipeline_posts),
                "recommended": len(selected),
                "needs_review": len(review),
                "rejected": rejected,
                "already_reported": already_reported,
                "duplicate": duplicate,
            }
            report = [
                f"# {pipeline.upper()} job report",
                "",
                f"Generated: {now.isoformat()}",
                "Window: rolling seven days by first discovery or material change.",
                "Counts: "
                + "; ".join(f"{key}={value}" for key, value in counts.items()),
                "",
                "## Recommendations",
                "",
            ]
            for post, result in selected:
                report.append(_entry(post, result, now))
                if profile is not None:
                    letter_path = (
                        directory
                        / "letters"
                        / f"{post.id}-r{post.revision}-{pipeline}.txt"
                    )
                    _atomic_write(letter_path, cover_letter(post, profile))
                    report.append(f"Private cover-letter draft: {letter_path}\n")
                    summary["letters"] += 1
            report.extend(["## Needs review", ""])
            report.extend(_entry(post, result, now) for post, result in review)
            path = directory / f"{stamp}-{pipeline}.md"
            _atomic_write(path, "\n".join(report))
            for post, _ in selected:
                session.add(
                    Delivery(
                        posting_id=post.id,
                        revision=post.revision,
                        pipeline=pipeline,
                        channel="local_report",
                        status="sent",
                        artifact_path=str(path),
                        sent_at=now,
                    )
                )
            summary["paths"].append(str(path))
            summary["pipelines"][pipeline] = counts
    return summary


def _telegram(client: httpx.Client, token: str, chat: str, text: str) -> str:
    for attempt in range(3):
        try:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat,
                    "text": text[:4000],
                    "link_preview_options": {"is_disabled": True},
                },
                timeout=httpx.Timeout(15, connect=5),
                follow_redirects=False,
            )
            payload = response.json()
            if response.status_code == 200 and payload.get("ok") is True:
                return "sent"
            if response.status_code == 429 and attempt < 2:
                delay = payload.get("parameters", {}).get("retry_after", 1)
                if type(delay) is int and 0 <= delay <= 30:
                    time.sleep(max(delay, 1))
                    continue
            return "uncertain" if response.status_code >= 500 else "failed"
        except (httpx.RequestError, ValueError, AttributeError):
            return "uncertain"
    return "failed"


def notify_jobs(
    engine: Engine,
    output_dir: str | Path,
    *,
    profile_path: str | Path | None = None,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
    client: httpx.Client | None = None,
) -> dict:
    if client is None:
        with httpx.Client(trust_env=False, follow_redirects=False) as owned:
            return notify_jobs(
                engine,
                output_dir,
                profile_path=profile_path,
                telegram_token=telegram_token,
                telegram_chat_id=telegram_chat_id,
                client=owned,
            )
    fingerprint = (
        profile_fingerprint(load_profile(profile_path)) if profile_path else None
    )
    counts = {"local": 0, "telegram": 0, "failed": 0, "uncertain": 0}
    now = utc_now()
    pending = []
    with Session(engine) as session, session.begin():
        session.execute(
            update(Delivery).where(Delivery.id == -1).values(status="pending")
        )
        posts = _recent_posts(session, now)
        results = _current_results(session, posts, fingerprint)
        sent_keys: dict[tuple[str, str], set] = {}
        for receipt in session.scalars(
            select(Delivery).where(Delivery.channel.in_(["local_alert", "telegram"]))
        ):
            # Explicit API rejection is safe to retry on the next scheduled
            # invocation. Sending/uncertain receipts may already be delivered.
            if receipt.channel == "telegram" and receipt.status == "failed":
                continue
            post = session.get(Posting, receipt.posting_id)
            if post is not None and post.revision == receipt.revision:
                sent_keys.setdefault((receipt.pipeline, receipt.channel), set()).update(
                    _keys(post)
                )
        for post in posts:
            if post.discovery_kind != "new" and post.revision == 1:
                continue
            for pipeline in ("us", "international"):
                if pipeline not in pipelines_for(post.locations):
                    continue
                result = results.get((post.id, pipeline))
                if _disposition(result) not in {"recommend", "stretch"}:
                    continue
                text = f"{pipeline.upper()} promising role\n" + _entry(
                    post, result, now
                )
                for channel in ("local_alert", "telegram"):
                    if channel == "telegram" and not (
                        telegram_token and telegram_chat_id
                    ):
                        continue
                    existing = session.scalar(
                        select(Delivery).where(
                            Delivery.posting_id == post.id,
                            Delivery.revision == post.revision,
                            Delivery.pipeline == pipeline,
                            Delivery.channel == channel,
                        )
                    )
                    if existing is not None and not (
                        channel == "telegram" and existing.status == "failed"
                    ):
                        continue
                    keys = _keys(post)
                    channel_keys = sent_keys.setdefault((pipeline, channel), set())
                    if keys & channel_keys:
                        continue
                    channel_keys.update(keys)
                    path = (
                        Path(output_dir)
                        / "alerts"
                        / f"{post.id}-r{post.revision}-{pipeline}.txt"
                    )
                    if channel == "local_alert":
                        _atomic_write(path, text)
                        counts["local"] += 1
                    if existing is None:
                        receipt = Delivery(
                            posting_id=post.id,
                            revision=post.revision,
                            pipeline=pipeline,
                            channel=channel,
                            status="sent" if channel == "local_alert" else "sending",
                            artifact_path=str(path),
                            sent_at=now if channel == "local_alert" else None,
                        )
                        session.add(receipt)
                    else:
                        receipt = existing
                        receipt.status = "sending"
                        receipt.sent_at = None
                    session.flush()
                    if channel == "telegram":
                        pending.append((receipt.id, text))
    for identity, text in pending:
        state = _telegram(client, telegram_token, telegram_chat_id, text)
        with Session(engine) as session, session.begin():
            receipt = session.get(Delivery, identity)
            receipt.status = state
            receipt.sent_at = utc_now() if state == "sent" else None
        counts["telegram" if state == "sent" else state] += 1
        if len(pending) > 1:
            time.sleep(1)
    return counts
