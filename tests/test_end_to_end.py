"""Synthetic end-to-end acceptance run; no live HTTP or private owner data."""

import json
from pathlib import Path

import httpx
from conftest import gemini_client
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobsfinder_io.discovery import discover
from jobsfinder_io.ingestion.polling import poll_source
from jobsfinder_io.persistence.models import (
    Delivery,
    Employer,
    JobSource,
    PollRun,
    Posting,
    ScreeningResult,
)
from jobsfinder_io.reporting import generate_reports, notify_jobs
from jobsfinder_io.runlock import database_run_lock
from jobsfinder_io.screening import screen_jobs_individual as screen_jobs
from jobsfinder_io.sources.adapters import make_collector


def test_complete_offline_discovery_monitor_screen_report_pipeline(
    database, tmp_path, monkeypatch
):
    """Two discovered employers, baseline + new IDs, AI, reports and safe replay."""
    monkeypatch.setattr(
        "jobsfinder_io.discovery.network.resolve_public",
        lambda host: "93.184.216.34",
    )
    monkeypatch.setattr("jobsfinder_io.discovery.network.time.sleep", lambda _: None)
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            [
                {"name": "Synthetic US", "careers_url": "https://us.example/careers"},
                {
                    "name": "Synthetic International",
                    "careers_url": "https://intl.example/careers",
                },
            ]
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "facts": ["I built a synthetic Python inventory service."],
                "skills": ["Python", "SQL"],
                "available_from": "2027-06-01",
                "international": {"priority_countries": ["Germany"]},
            }
        ),
        encoding="utf-8",
    )
    state = {"phase": "baseline", "fail_greenhouse": False}
    ai_requests = []

    def green_job(identity):
        return {
            "id": identity,
            "title": "Backend Engineer",
            "absolute_url": f"https://boards.greenhouse.io/us/jobs/{identity}",
            "content": "<p>Build Python services. Experience preferred.</p>",
            "location": {"name": "New York, United States"},
        }

    def lever_job():
        return {
            "id": "int-1",
            "text": "Integration Engineer",
            "hostedUrl": "https://jobs.lever.co/intl/int-1",
            "applyUrl": "https://jobs.lever.co/intl/int-1/apply",
            "descriptionPlain": "Build Python services. Experience preferred.",
            "categories": {"location": "Berlin, Germany"},
        }

    def handle(request):
        host, path = request.url.host, request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if host in {"us.example", "intl.example"}:
            board = (
                "https://boards.greenhouse.io/us"
                if host == "us.example"
                else "https://jobs.lever.co/intl"
            )
            return httpx.Response(
                200,
                text=f'<a href="{board}">Official jobs</a>',
                headers={"content-type": "text/html"},
            )
        if host == "boards-api.greenhouse.io":
            if state["fail_greenhouse"]:
                return httpx.Response(403)
            if path.endswith("/jobs"):
                identities = (
                    [101] if state["phase"] in {"baseline", "missing"} else [101, 102]
                )
                jobs = [green_job(identity) for identity in identities]
                return httpx.Response(
                    200, json={"jobs": jobs, "meta": {"total": len(jobs)}}
                )
            return httpx.Response(200, json={"id": int(path.rsplit("/", 1)[-1])})
        if host == "api.lever.co":
            return httpx.Response(
                200, json=[] if state["phase"] == "baseline" else [lever_job()]
            )
        if host == "generativelanguage.googleapis.com":
            payload = json.loads(request.content)
            ai_requests.append(payload)
            posting = json.loads(payload["contents"][0]["parts"][0]["text"])["posting"]
            international_job = "Germany" in posting["locations"]
            us_pipeline = (
                "Pipeline: us." in payload["systemInstruction"]["parts"][0]["text"]
            )
            disposition = (
                "needs_review" if international_job and us_pipeline else "recommend"
            )
            evaluation = {
                "disposition": disposition,
                "score": 85 if disposition == "recommend" else 20,
                "primary_reason": "Programming-heavy role; immigration unconfirmed.",
                "visa_class": "B",
                "start_class": "B",
                "required_experience": None,
                "preferred_experience": "Experience preferred.",
                "country": "Germany" if international_job else "United States",
                "uncertainty": ["Employer sponsorship not stated."],
                "requires_human_review": True,
                "evidence": [
                    {"quote": "Build Python services.", "source_url": posting["url"]}
                ],
            }
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "role": "model",
                                "parts": [{"text": json.dumps(evaluation)}],
                            },
                        }
                    ],
                    "usageMetadata": {"totalTokenCount": 100},
                },
            )
        raise AssertionError(f"Unexpected request {request.method} {request.url}")

    engine = database[1]
    with (
        database_run_lock(database[0]),
        httpx.Client(transport=httpx.MockTransport(handle)) as client,
        gemini_client(transport=httpx.MockTransport(handle)) as ai_client,
    ):
        assert discover(engine, candidates, client=client)["registered"] == 2
        assert discover(engine, candidates, client=client)["duplicates"] == 2
        with Session(engine) as session:
            sources = [
                (s.id, s.provider)
                for s in session.scalars(select(JobSource).order_by(JobSource.id))
            ]
        summaries = [
            poll_source(
                engine,
                identity,
                collector=make_collector(provider, client, request_interval=0),
            )
            for identity, provider in sources
        ]
        assert sum(s.baseline for s in summaries) == 1
        assert all(s.status == "complete_success" for s in summaries)
        state["phase"] = "new"
        summaries = [
            poll_source(
                engine,
                identity,
                collector=make_collector(provider, client, request_interval=0),
            )
            for identity, provider in sources
        ]
        assert sum(s.new for s in summaries) == 2
        for identity, provider in sources:
            repeat = poll_source(
                engine,
                identity,
                collector=make_collector(provider, client, request_interval=0),
            )
            assert repeat.new == 0
            assert repeat.status == "complete_success"
        screening = screen_jobs(
            engine, profile, api_key="synthetic-placeholder", client=ai_client
        )
        assert screening["api_calls"] >= 6
        assert (
            screen_jobs(
                engine, profile, api_key="synthetic-placeholder", client=ai_client
            )["api_calls"]
            == 0
        )
        report = generate_reports(engine, tmp_path / "reports", profile_path=profile)
        assert report["pipelines"]["us"]["recommended"] == 2
        assert report["pipelines"]["international"]["recommended"] == 1
        assert report["letters"] == 3
        for path in report["paths"]:
            text = Path(path).read_text(encoding="utf-8")
            assert "Employer sponsorship not stated." in text
            assert "freshness uncertain" in text
        alerts = notify_jobs(engine, tmp_path / "reports")
        assert alerts["local"] == 2
        assert alerts["telegram"] == 0
        repeated = generate_reports(engine, tmp_path / "reports", profile_path=profile)
        assert all(
            result["recommended"] == 0 for result in repeated["pipelines"].values()
        )
        assert notify_jobs(engine, tmp_path / "reports")["local"] == 0

        # Failed fetches preserve all active records and their eligibility data.
        greenhouse_id = next(
            identity for identity, provider in sources if provider == "greenhouse"
        )
        state["fail_greenhouse"] = True
        failure = poll_source(
            engine,
            greenhouse_id,
            collector=make_collector("greenhouse", client, request_interval=0),
        )
        assert failure.status == "failed"
        with Session(engine) as session:
            assert set(session.scalars(select(Posting.status))) == {"active"}
        state["fail_greenhouse"] = False
        state["phase"] = "missing"
        assert (
            poll_source(
                engine,
                greenhouse_id,
                collector=make_collector("greenhouse", client, request_interval=0),
            ).missing
            == 1
        )
        assert (
            poll_source(
                engine,
                greenhouse_id,
                collector=make_collector("greenhouse", client, request_interval=0),
            ).closed
            == 1
        )
        state["phase"] = "new"
        reappeared = poll_source(
            engine,
            greenhouse_id,
            collector=make_collector("greenhouse", client, request_interval=0),
        )
        assert reappeared.reappeared == 1
        assert (
            screen_jobs(
                engine, profile, api_key="synthetic-placeholder", client=ai_client
            )["api_calls"]
            == 0
        )
        assert (
            generate_reports(engine, tmp_path / "reports", profile_path=profile)[
                "pipelines"
            ]["us"]["recommended"]
            == 1
        )
        assert notify_jobs(engine, tmp_path / "reports")["local"] == 1

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Employer)) == 2
        assert session.scalar(select(func.count()).select_from(JobSource)) == 2
        assert session.scalar(select(func.count()).select_from(Posting)) == 3
        assert session.scalar(select(func.count()).select_from(Delivery)) == 7
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScreeningResult)
                .where(ScreeningResult.stage == "final")
            )
            >= 3
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PollRun)
                .where(PollRun.status == "failed")
            )
            == 1
        )
        assert set(session.scalars(select(Posting.status))) == {"active"}
    assert len(ai_requests) == screening["api_calls"]
