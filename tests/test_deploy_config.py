import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "deploy_verify_config",
    Path(__file__).resolve().parents[1] / "deploy/verify_config.py",
)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def test_validation_supplies_disposable_empty_environment(monkeypatch):
    monkeypatch.setenv("JOBSFINDER_RUNTIME_ENV", "/private/must-not-read.env")
    stand_ins = []

    def render(args, *, env, **kwargs):
        assert "--no-env-resolution" not in args
        runtime = Path(env["JOBSFINDER_RUNTIME_ENV"])
        assert runtime.is_file() and runtime.read_bytes() == b""
        assert runtime != Path("/private/must-not-read.env")
        stand_ins.append(runtime)
        service = {
            "user": "1000:1000",
            "read_only": True,
            "mem_limit": "536870912",
            "memswap_limit": "536870912",
            "pull_policy": "never",
            "volumes": [{"target": "/app/data"}],
            "env_file": [{"path": str(runtime), "format": "raw"}],
            "environment": {
                "JOBSFINDER_PROFILE": "/app/data/private/profile.json",
                "JOBSFINDER_CANDIDATES": "/app/data/private/candidates.json",
                "JOBSFINDER_REPORT_DIR": "/app/data/reports",
            },
        }
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"services": {"jobsfinder": service}}),
            stderr="",
        )

    monkeypatch.setattr(validator.subprocess, "run", render)
    validator.verify_config()
    assert stand_ins and not stand_ins[0].exists()


def test_validation_reports_compose_error_without_dumping_config(monkeypatch):
    monkeypatch.setattr(
        validator.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout="do not dump rendered environment",
            stderr="unknown flag: --no-env-resolution\n",
        ),
    )
    with pytest.raises(SystemExit) as error:
        validator.verify_config()
    assert "unknown flag: --no-env-resolution" in str(error.value)
    assert "Compose 2.30+" in str(error.value)
    assert "rendered environment" not in str(error.value)
