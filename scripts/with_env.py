"""Run a command with this checkout's ignored local environment file."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
    if line.strip() and not line.startswith("#"):
        key, value = line.split("=", 1)
        environment[key] = value
if len(sys.argv) < 2:
    raise SystemExit("Usage: python scripts/with_env.py <command> [arguments]")
raise SystemExit(subprocess.call(sys.argv[1:], env=environment, cwd=root))
