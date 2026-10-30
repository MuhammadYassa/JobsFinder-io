"""Network-free smoke of the actual release image; receives no private mounts."""

import os
import subprocess
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

assert os.getuid() == 1000
assert Path("/app/deploy/compose.yaml").is_file()
assert not Path("/app/.env").exists()
assert not list(Path("/app/data").iterdir())
with tempfile.TemporaryDirectory() as directory:
    database = Path(directory) / "smoke.db"
    config = Config("/app/alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite:///" + str(database))
    command.upgrade(config, "head")
    command.check(config)
    subprocess.run(["jobsfinder-io", "--db", str(database), "health"], check=True)
print("Release image: non-root, private files absent, migrations and health passed")
