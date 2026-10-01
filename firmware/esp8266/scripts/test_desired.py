"""Host fault tests for ESP8266 desired-state persistence; no board required."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="appliance-8266-") as directory:
    executable = str(Path(directory) / "desired-test")
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-g",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        "-I", str(root / "main"), str(root / "main/desired_state.c"),
        str(root / "tests/desired_test.c"), "-o", executable,
    ], check=True)
    subprocess.run([executable], check=True)
