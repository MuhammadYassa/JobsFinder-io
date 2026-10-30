"""Validate production Compose without opening any credentials or data files."""

import json
import os
import subprocess
from pathlib import Path

env = os.environ.copy()
env["JOBSFINDER_RELEASE_IMAGE"] = "ghcr.io/example/jobsfinder@sha256:" + "a" * 64
result = subprocess.run(
    [
        "docker",
        "compose",
        "--env-file",
        os.devnull,
        "-f",
        str(Path(__file__).with_name("compose.yaml")),
        "config",
        "--no-env-resolution",
        "--format",
        "json",
    ],
    env=env,
    capture_output=True,
    text=True,
    check=True,
)
service = json.loads(result.stdout)["services"]["jobsfinder"]
assert "build" not in service and not service.get("ports")
assert service["user"] == "1000:1000" and service["read_only"]
assert int(service["mem_limit"]) == int(service["memswap_limit"]) == 512 * 1024**2
assert service["pull_policy"] == "never"
assert service["volumes"][0]["target"] == "/app/data"
assert service["env_file"][0]["format"] == "raw"
print(
    "Production Compose: no builds/ports, private env, persistent data, 512 MiB bound"
)
