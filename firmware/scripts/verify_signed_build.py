"""Compile a signing-enabled ESP32 image and exercise host signature verification.

Run only inside the official ESP-IDF container. Signing keys are temporary test
material in the container and are never printed or copied into the repository.
This proves host cryptographic checks, not device boot, OTA or power-cut behaviour.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if (result.returncode == 0) != expect_ok:
        raise RuntimeError(f"Unexpected exit status {result.returncode}: {result.stdout[-4000:]}")
    return result


def secure(*args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, "-m", "espsecure", *args, expect_ok=expect_ok)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    if not os.environ.get("IDF_PATH"):
        raise SystemExit("Run inside espressif/idf:v5.5; no hardware is accessed.")
    ordinary = subprocess.run(["idf.py", "build"])
    if ordinary.returncode:
        raise SystemExit(ordinary.returncode)
    key_dir = Path("/keys")
    key_dir.mkdir(mode=0o700, exist_ok=True)
    signing_key = key_dir / "ota-signing-key.pem"
    if signing_key.exists():
        raise SystemExit("Refusing to replace an existing signing key; use a fresh compiler container.")
    secure("generate_signing_key", "--version", "1", str(signing_key))
    build = subprocess.run([
        "idf.py", "-B", "build-signed", "-D", f"SDKCONFIG={root / 'sdkconfig.signed'}",
        "-D", "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.signed.defaults", "build"
    ])
    if build.returncode:
        raise SystemExit(build.returncode)
    config = (root / "sdkconfig.signed").read_text()
    required = [
        "CONFIG_SECURE_SIGNED_APPS_NO_SECURE_BOOT=y",
        "CONFIG_SECURE_SIGNED_ON_UPDATE_NO_SECURE_BOOT=y",
        "CONFIG_SECURE_SIGNED_APPS_ECDSA_SCHEME=y",
    ]
    if any(flag not in config for flag in required) or "\nCONFIG_SECURE_BOOT=y\n" in config:
        raise RuntimeError("Signed-update configuration does not match the software-only profile")
    artifact = root / "build-signed" / "appliance_device.bin"
    public_key = key_dir / "ota-public-key.pem"
    secure("extract_public_key", "--version", "1", "--keyfile", str(signing_key), str(public_key))
    secure("verify_signature", "--version", "1", "--keyfile", str(public_key), str(artifact))
    with tempfile.TemporaryDirectory(prefix="appliance-signature-test-") as temporary:
        temp = Path(temporary)
        modified = temp / "modified.bin"
        damaged = bytearray(artifact.read_bytes())
        damaged[100] ^= 1
        modified.write_bytes(damaged)
        secure("verify_signature", "--version", "1", "--keyfile", str(public_key), str(modified), expect_ok=False)
        wrong = temp / "wrong-key.pem"
        secure("generate_signing_key", "--version", "1", str(wrong))
        wrong_public = temp / "wrong-public.pem"
        secure("extract_public_key", "--version", "1", "--keyfile", str(wrong), str(wrong_public))
        secure("verify_signature", "--version", "1", "--keyfile", str(wrong_public), str(artifact), expect_ok=False)
        unsigned = root / "build" / "appliance_device.bin"
        if not unsigned.exists():
            raise RuntimeError("Build the ordinary unsigned profile first")
        secure("verify_signature", "--version", "1", "--keyfile", str(public_key), str(unsigned), expect_ok=False)
    evidence = {
        "scope": "host image-signature checks only; no device or OTA transport exercised",
        "artifact": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "bytes": artifact.stat().st_size,
        "valid_signature": "accepted",
        "modified_image": "rejected",
        "wrong_key": "rejected",
        "unsigned_image": "rejected",
        "hardware_secure_boot_enabled": False,
    }
    (root / "build-signed" / "signature-verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
