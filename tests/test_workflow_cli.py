"""Cron commands remain useful without optional credentials."""

import json

from jobsfinder_io.cli import build_parser, main
from jobsfinder_io.runlock import database_run_lock


def test_empty_tick_and_health_without_credentials(
    database, tmp_path, monkeypatch, capsys
):
    for key in (
        "GEMINI_API_KEY",
        "JOBSFINDER_PROFILE",
        "JOBSFINDER_CANDIDATES",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    args = ["--db", str(database[0])]
    assert main([*args, "run-due", "--output-dir", str(tmp_path / "reports")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["polling"]["due"] == 0
    assert result["screening"]["skipped"] == 1
    assert result["discovery"]["status"] == "not_configured"
    assert main([*args, "health"]) == 0
    assert json.loads(capsys.readouterr().out)["postings"] == 0


def test_cli_overlap_and_invalid_private_input(database, tmp_path, capsys):
    args = ["--db", str(database[0])]
    with database_run_lock(database[0]):
        assert main([*args, "poll-due"]) == 1
    assert "Another workflow" in capsys.readouterr().err
    profile = tmp_path / "profile.json"
    profile.write_text("secret malformed profile", encoding="utf-8")
    assert main([*args, "screen", "--profile", str(profile)]) == 1
    assert "secret" not in capsys.readouterr().err


def test_failure_exit_code_preserves_operational_summary(database, monkeypatch, capsys):
    monkeypatch.setattr(
        "jobsfinder_io.operations.poll_due",
        lambda engine: {"due": 2, "success": 1, "failed": 1},
    )
    assert main(["--db", str(database[0]), "poll-due"]) == 1
    assert json.loads(capsys.readouterr().out)["success"] == 1


def test_uncertain_delivery_is_visible_to_cron(database, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "jobsfinder_io.reporting.non_ai.notify_jobs",
        lambda *args, **kwargs: {
            "local": 1,
            "telegram": 0,
            "failed": 0,
            "uncertain": 1,
        },
    )
    assert (
        main(["--db", str(database[0]), "notify", "--output-dir", str(tmp_path)]) == 1
    )
    assert json.loads(capsys.readouterr().out)["uncertain"] == 1


def test_gemini_environment_settings_reach_screening(database, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-google-key")
    monkeypatch.setenv("GEMINI_PRELIMINARY_MODEL", "gemini-configurable-preliminary")
    monkeypatch.setenv("GEMINI_REVIEW_MODEL", "gemini-configurable-review")
    monkeypatch.setenv("GEMINI_MAX_CALLS", "7")
    captured = {}

    def screen(*args, **kwargs):
        captured.update(kwargs)
        return {"api_calls": 0}

    monkeypatch.setattr("jobsfinder_io.screening.screen_jobs", screen)
    assert main(["--db", str(database[0]), "screen"]) == 0
    assert captured == {
        "api_key": "fake-google-key",
        "preliminary_model": "gemini-configurable-preliminary",
        "review_model": "gemini-configurable-review",
        "max_calls": 7,
    }
    capsys.readouterr()


def test_legacy_openai_key_is_never_used(database, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-legacy-key")
    keys = []

    def screen(*args, **kwargs):
        keys.append(kwargs["api_key"])
        return {"api_calls": 0}

    monkeypatch.setattr("jobsfinder_io.screening.screen_jobs", screen)
    assert main(["--db", str(database[0]), "screen"]) == 0
    assert keys == [None]
    capsys.readouterr()


def test_default_model_is_gemini(monkeypatch):
    for name in ("GEMINI_PRELIMINARY_MODEL", "GEMINI_REVIEW_MODEL"):
        monkeypatch.delenv(name, raising=False)
    args = build_parser().parse_args(["screen"])
    assert args.preliminary_model == args.review_model == "gemini-3.8-flash"


def test_screen_cli_forwards_only_selected_postings(database, monkeypatch):
    selected = []

    def screen(*args, **kwargs):
        selected.extend(kwargs["posting_ids"])
        return {"api_calls": 0}

    monkeypatch.setattr("jobsfinder_io.screening.screen_jobs", screen)
    assert (
        main(
            [
                "--db",
                str(database[0]),
                "screen",
                "--posting-id",
                "34",
                "--posting-id",
                "68",
            ]
        )
        == 0
    )
    assert selected == [34, 68]


def test_no_retries_cli_is_forwarded(database, monkeypatch):
    attempts = []

    def screen(*args, **kwargs):
        attempts.append(kwargs["max_attempts"])
        return {"api_calls": 0}

    monkeypatch.setattr("jobsfinder_io.screening.screen_jobs", screen)
    assert (
        main(["--db", str(database[0]), "screen", "--posting-id", "68", "--no-retries"])
        == 0
    )
    assert attempts == [1]


def test_email_test_missing_settings_fails_without_sending(
    database, monkeypatch, capsys
):
    for name in ("SMTP_HOST", "SMTP_FROM", "SMTP_TO"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--db", str(database[0]), "test-email"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "missing_config",
        "sent": 0,
    }


def test_local_only_report_never_processes_outbox(
    database, tmp_path, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Local-only report attempted SMTP")

    monkeypatch.setattr("jobsfinder_io.delivery.deliver_pending", forbidden)
    assert (
        main(
            [
                "--db",
                str(database[0]),
                "report",
                "--local-only",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["count"] == 0
    assert "email" not in result
