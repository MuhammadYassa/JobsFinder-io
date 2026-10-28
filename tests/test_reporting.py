import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import Delivery, Posting, ScreeningResult, utc_now
from jobsfinder_io.registry import add_employer, add_source
from jobsfinder_io.reporting import cover_letter, generate_reports, notify_jobs
from jobsfinder_io.screening import load_profile, profile_fingerprint


@pytest.fixture
def private_profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "facts": [
                    "I built a synthetic inventory service using Python and SQLite."
                ],
                "skills": ["Python", "SQL"],
            }
        ),
        encoding="utf-8",
    )
    return path


def seed(
    engine,
    *,
    identity="1",
    source_id=None,
    hash_value="hash",
    revision=1,
    seen=None,
    changed=None,
    disposition="recommend",
    pipeline="us",
    stage="final",
    profile_hash="profile",
    score=80,
    url=None,
    kind="new",
    country="Germany",
):
    now = utc_now()
    with Session(engine) as session, session.begin():
        if source_id is None:
            employer = add_employer(session, "Synthetic employer")
            source = add_source(
                session,
                employer.id,
                "greenhouse",
                f"example-{identity}",
                "https://example.test/careers",
            )
            source_id = source.id
        post = Posting(
            source_id=source_id,
            external_posting_id=identity,
            title="Software Engineer",
            canonical_job_url=url or f"https://example.test/jobs/{identity}",
            apply_url=url or f"https://example.test/jobs/{identity}",
            description_text="Build Python services.",
            date_provenance="unknown",
            first_seen_at=seen or now,
            last_seen_at=now,
            last_changed_at=changed or seen or now,
            content_hash=hash_value,
            revision=revision,
            discovery_kind=kind,
            status="active",
            locations="United States" if pipeline == "us" else "Germany",
        )
        session.add(post)
        session.flush()
        result = ScreeningResult(
            posting_id=post.id,
            content_hash=hash_value,
            profile_hash=profile_hash,
            policy_version="v1",
            prompt_version="v1",
            model="mock",
            stage=stage,
            pipeline=pipeline,
            disposition=disposition,
            score=score,
            payload={
                "primary_reason": "Relevant software role.",
                "country": country,
                "visa_class": "B",
                "start_class": "B",
                "uncertainty": ["Sponsorship unknown."],
                "evidence": [
                    {
                        "quote": "Build Python services.",
                        "source_url": post.canonical_job_url,
                    }
                ],
            },
        )
        session.add(result)
        return post.id, source_id


def test_report_window_counts_dates_and_persistent_dedup(database, tmp_path):
    engine = database[1]
    now = utc_now()
    seed(engine, identity="new")
    seed(engine, identity="missed", seen=now - timedelta(days=6))
    seed(
        engine,
        identity="changed",
        seen=now - timedelta(days=40),
        changed=now,
        revision=2,
    )
    seed(engine, identity="stale", seen=now - timedelta(days=8))
    seed(engine, identity="review", disposition="needs_review")
    seed(engine, identity="reject", disposition="reject")
    output = generate_reports(
        engine, tmp_path / "reports", now=now + timedelta(seconds=1)
    )
    assert output["pipelines"]["us"] == {
        "stored_active_in_window": 5,
        "recommended": 3,
        "needs_review": 1,
        "rejected": 1,
        "already_reported": 0,
        "duplicate": 0,
    }
    text = Path(output["paths"][0]).read_text(encoding="utf-8")
    assert "freshness uncertain" in text
    assert "Source publication: unknown" in text
    assert "Sponsorship unknown" in text
    assert "Build Python services." in text
    repeat = generate_reports(
        engine, tmp_path / "reports", now=now + timedelta(seconds=2)
    )
    assert repeat["pipelines"]["us"]["recommended"] == 0
    assert repeat["pipelines"]["us"]["already_reported"] == 3


def test_report_current_content_and_final_result_only(database, tmp_path):
    engine = database[1]
    identity, _ = seed(engine)
    with Session(engine) as session, session.begin():
        post = session.get(Posting, identity)
        post.content_hash = "changed-hash"
    output = generate_reports(engine, tmp_path)
    assert output["pipelines"]["us"]["recommended"] == 0
    assert output["pipelines"]["us"]["needs_review"] == 1


def test_report_cross_source_dedup_preserves_distinct_roles(database, tmp_path):
    engine = database[1]
    _, source_id = seed(
        engine, identity="one", url="https://example.test/jobs/shared?utm_source=feed"
    )
    seed(
        engine,
        identity="two",
        source_id=source_id,
        url="https://example.test/jobs/shared#apply",
    )
    seed(engine, identity="three", source_id=source_id)
    result = generate_reports(engine, tmp_path)
    assert result["pipelines"]["us"]["recommended"] == 2
    assert result["pipelines"]["us"]["duplicate"] == 1


def test_letters_use_private_facts_and_word_limits(database, tmp_path, private_profile):
    engine = database[1]
    profile = load_profile(private_profile)
    identity, _ = seed(engine, profile_hash=profile_fingerprint(profile))
    output = generate_reports(
        engine, tmp_path / "reports", profile_path=private_profile
    )
    assert output["letters"] == 1
    letter = next((tmp_path / "reports" / "letters").glob("*.txt")).read_text(
        encoding="utf-8"
    )
    assert 100 <= len(letter.split()) <= 160
    assert profile["facts"][0] in letter
    assert "Python, SQL" in letter
    assert "internship" not in letter
    with Session(engine) as session:
        post = session.get(Posting, identity)
        assert 100 <= len(cover_letter(post, {}).split()) <= 160


def test_private_profile_hash_excludes_old_results(database, tmp_path, private_profile):
    seed(database[1], profile_hash="old")
    result = generate_reports(database[1], tmp_path, profile_path=private_profile)
    assert result["pipelines"]["us"]["recommended"] == 0


def test_report_write_failure_does_not_mark_delivered(database, tmp_path, monkeypatch):
    import jobsfinder_io.reporting as reporting

    seed(database[1])
    monkeypatch.setattr(
        reporting,
        "_atomic_write",
        lambda *args: (_ for _ in ()).throw(OSError("synthetic")),
    )
    with pytest.raises(OSError):
        generate_reports(database[1], tmp_path)
    with Session(database[1]) as session:
        assert list(session.scalars(select(Delivery))) == []


def test_notifications_local_fallback_and_no_duplicates(database, tmp_path):
    seed(database[1])
    first = notify_jobs(database[1], tmp_path)
    assert first == {"local": 1, "telegram": 0, "failed": 0, "uncertain": 0}
    assert len(list((tmp_path / "alerts").glob("*.txt"))) == 1
    assert notify_jobs(database[1], tmp_path)["local"] == 0


@pytest.mark.parametrize(
    "outcome", ["success", "timeout", "server_error", "unauthorized"]
)
def test_telegram_receipts_prevent_replay(database, tmp_path, outcome):
    seed(database[1])
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.host == "api.telegram.org"
        body = json.loads(request.content)
        assert body["chat_id"] == "synthetic-chat"
        assert "parse_mode" not in body
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        status = {"success": 200, "server_error": 500, "unauthorized": 401}[outcome]
        return httpx.Response(status, json={"ok": status == 200})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = notify_jobs(
            database[1],
            tmp_path,
            telegram_token="synthetic",
            telegram_chat_id="synthetic-chat",
            client=client,
        )
        repeat = notify_jobs(
            database[1],
            tmp_path,
            telegram_token="synthetic",
            telegram_chat_id="synthetic-chat",
            client=client,
        )
    assert len(requests) == (2 if outcome == "unauthorized" else 1)
    assert repeat["telegram"] == 0
    if outcome == "success":
        assert result["telegram"] == 1
    elif outcome == "unauthorized":
        assert result["failed"] == 1
    else:
        assert result["uncertain"] == 1


def test_telegram_rate_limit_retry_is_bounded(database, tmp_path, monkeypatch):
    import jobsfinder_io.reporting as reporting

    seed(database[1])
    requests = []
    sleeps = []
    monkeypatch.setattr(reporting.time, "sleep", sleeps.append)

    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 2}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = notify_jobs(
            database[1],
            tmp_path,
            telegram_token="synthetic",
            telegram_chat_id="synthetic-chat",
            client=client,
        )
    assert len(requests) == 3
    assert sleeps == [2, 2]
    assert result["failed"] == 1


def test_baseline_not_fast_alerted(database, tmp_path):
    seed(database[1], kind="baseline")
    assert notify_jobs(database[1], tmp_path)["local"] == 0


def test_notification_profile_change_blocks_stale_result(
    database, tmp_path, private_profile
):
    seed(database[1], profile_hash="previous-profile")
    result = notify_jobs(database[1], tmp_path, profile_path=private_profile)
    assert result["local"] == 0
    assert not list((tmp_path / "alerts").glob("*.txt"))


def test_invalid_notification_profile_has_no_side_effects(database, tmp_path):
    seed(database[1])
    profile = tmp_path / "broken.json"
    profile.write_text("invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        notify_jobs(database[1], tmp_path, profile_path=profile)
    with Session(database[1]) as session:
        assert list(session.scalars(select(Delivery))) == []


def test_telegram_explicit_rejection_retries_same_receipt(database, tmp_path):
    seed(database[1])
    calls = []

    def handler(request):
        calls.append(request)
        status = 401 if len(calls) == 1 else 200
        return httpx.Response(status, json={"ok": status == 200})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = notify_jobs(
            database[1],
            tmp_path,
            telegram_token="synthetic",
            telegram_chat_id="synthetic",
            client=client,
        )
        second = notify_jobs(
            database[1],
            tmp_path,
            telegram_token="synthetic",
            telegram_chat_id="synthetic",
            client=client,
        )
        third = notify_jobs(
            database[1],
            tmp_path,
            telegram_token="synthetic",
            telegram_chat_id="synthetic",
            client=client,
        )
    assert first["failed"] == 1
    assert second["telegram"] == 1
    assert third["telegram"] == 0
    assert len(calls) == 2
    with Session(database[1]) as session:
        assert len(list(session.scalars(select(Delivery)))) == 2


def test_reports_respect_pipeline_routing(database, tmp_path):
    identity, _ = seed(database[1])
    with Session(database[1]) as session, session.begin():
        session.get(Posting, identity).locations = "United States"
    result = generate_reports(database[1], tmp_path)
    assert result["pipelines"]["us"]["stored_active_in_window"] == 1
    assert result["pipelines"]["international"]["stored_active_in_window"] == 0
    assert result["pipelines"]["international"]["needs_review"] == 0


def test_incomplete_preliminary_does_not_recommend(database, tmp_path):
    seed(database[1], stage="preliminary")
    result = generate_reports(database[1], tmp_path)
    assert result["pipelines"]["us"]["recommended"] == 0
    assert result["pipelines"]["us"]["needs_review"] == 1
    assert notify_jobs(database[1], tmp_path)["local"] == 0


def test_notification_cross_source_alias_not_repeated(database, tmp_path):
    _, source_id = seed(
        database[1], identity="first", url="https://example.test/shared"
    )
    seed(
        database[1],
        identity="second",
        source_id=source_id,
        url="https://example.test/shared?utm_source=feed",
    )
    assert notify_jobs(database[1], tmp_path)["local"] == 1
    assert notify_jobs(database[1], tmp_path)["local"] == 0


def test_dedup_preserves_meaningful_query_and_fragment(database, tmp_path):
    _, source_id = seed(
        database[1],
        identity="first",
        url="https://example.test/careers?source=division1#/job1",
    )
    seed(
        database[1],
        identity="second",
        source_id=source_id,
        url="https://example.test/careers?source=division2#/job2",
    )
    assert (
        generate_reports(database[1], tmp_path)["pipelines"]["us"]["recommended"] == 2
    )


def test_material_change_recommended_again(database, tmp_path):
    identity, _ = seed(database[1])
    assert (
        generate_reports(database[1], tmp_path)["pipelines"]["us"]["recommended"] == 1
    )
    with Session(database[1]) as session, session.begin():
        session.get(Posting, identity).revision += 1
    assert (
        generate_reports(database[1], tmp_path)["pipelines"]["us"]["recommended"] == 1
    )
