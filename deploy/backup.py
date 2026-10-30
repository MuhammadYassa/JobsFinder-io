"""Create a consistent SQLite backup without overwriting existing files."""

import argparse
import os
from pathlib import Path

from host import backup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
os.umask(0o077)
backup(args.source, args.destination)
print("SQLite backup and integrity check passed")
