"""Validate production Compose with a disposable, empty credential-file stand-in."""

import json
import os
import subprocess
import tempfile
from pathlib import Path


def verify_config() -> None:
    env = os.environ.copy()
    env["JOBSFINDER_RELEASE_IMAGE"] = "ghcr.io/example/jobsfinder@sha256:" + "a" * 64
    with tempfile.TemporaryDirectory(prefix="jobsfinder-compose-") as directory:
        runtime = Path(directory) / "runtime.env"
        runtime.write_text("", encoding="utf-8")
        # Rendering resolves env files. Never read private files or relax the
        # required production default, and use flags supported by Compose 2.30.
        env["JOBSFINDER_RUNTIME_ENV"] = str(runtime)
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                os.devnull,
                "-f",
                str(Path(__file__).with_name("compose.yaml")),
                "config",
                "--format",
                "json",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit(
                "Production Compose validation failed "
                f"(exit {result.returncode}; requires Compose 2.30+):\n"
                + result.stderr.strip()
            )
        service = json.loads(result.stdout)["services"]["jobsfinder"]
        assert "build" not in service and not service.get("ports")
        assert service["user"] == "1000:1000" and service["read_only"]
        assert (
            int(service["mem_limit"]) == int(service["memswap_limit"]) == 512 * 1024**2
        )
        assert service["pull_policy"] == "never"
        assert service["volumes"][0]["target"] == "/app/data"
        assert service["environment"] == {
            "JOBSFINDER_PROFILE": "/app/data/private/profile.json",
            "JOBSFINDER_CANDIDATES": "/app/data/private/candidates.json",
            "JOBSFINDER_REPORT_DIR": "/app/data/reports",
        }
    print(
        "Production Compose: no builds/ports, private env, persistent data, 512 MiB bound"
    )


if __name__ == "__main__":
    verify_config()
