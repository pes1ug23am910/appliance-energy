"""Compile the firmware spool core with host sanitizers; no board is required."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="appliance-spool-") as directory:
    executable = str(Path(directory) / "spool-test")
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-g",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        "-I", str(root / "main"), str(root / "main/telemetry_spool.c"),
        str(root / "tests/spool_test.c"), "-o", executable,
    ], check=True)
    subprocess.run([executable], check=True)
