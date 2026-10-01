"""Create local demo identities and TLS material; never print secrets."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
MOSQUITTO_IMAGE = "eclipse-mosquitto:2@sha256:38c0da4f2ef84284d47b3b3eeea1cb3bdeabe81ee10caf0cd5c5ff61ee3ea408"


def private_write(path: Path, content: bytes):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        if os.name != "nt":
            os.fchmod(handle.fileno(), 0o600)
        handle.write(content)


def directory(path: Path, mode: int):
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(mode)


def service_readable(path: Path):
    # The host's .runtime parent is 0700; Docker binds just the service subdirectory.
    if os.name != "nt":
        path.chmod(0o644)


def certificates(path: Path, private_path: Path):
    directory(path, 0o755)
    directory(private_path, 0o700)
    legacy_key = path / "ca.key"
    signing_key = private_path / "ca.key"
    if legacy_key.exists():
        if signing_key.exists():
            raise RuntimeError("CA keys exist in both locations; reconcile them before continuing")
        legacy_key.replace(signing_key)
        if os.name != "nt":
            signing_key.chmod(0o600)
    if (path / "server.crt").exists():
        for name in ("ca.crt", "server.key"):
            if not (path / name).exists():
                raise RuntimeError("Incomplete certificate directory; restore its matching files")
        for name in ("ca.crt", "server.crt", "server.key"):
            service_readable(path / name)
        return
    if any(path.iterdir()) or signing_key.exists():
        raise RuntimeError("Incomplete certificate directory; restore its matching files")
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Appliance local development CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
          .not_valid_after(now+timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mosquitto")]))
            .issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=180))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("mosquitto"), x509.DNSName("localhost"),
                          x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256()))
    private_write(signing_key, ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_write(path / "server.key", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (path / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (path / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    for name in ("ca.crt", "server.crt", "server.key"):
        service_readable(path / name)


def password_database(broker: Path, lines: list[str]):
    # Staging leaves a running broker's hashed database intact on failure.
    with tempfile.TemporaryDirectory(prefix=".passwords-", dir=broker) as temporary:
        stage = Path(temporary)
        output = stage / "passwords"
        private_write(output, ("\n".join(lines) + "\n").encode())
        identity = "0" if os.name == "nt" else f"{os.getuid()}:{os.getgid()}"
        subprocess.run(["docker", "run", "--rm", "--user", identity, "-v", f"{stage}:/work",
                        MOSQUITTO_IMAGE, "mosquitto_passwd", "-U", "/work/passwords"], check=True)
        service_readable(output)
        output.replace(broker / "passwords")


def bootstrap(devices: int, root: Path = ROOT):
    if not 1 <= devices <= 10000:
        raise ValueError("devices must be between 1 and 10000")
    runtime = root / ".runtime"
    directory(runtime, 0o700)
    broker = runtime / "mosquitto"
    directory(broker, 0o755)
    certificates(runtime / "certs", runtime / "private")
    env_path = root / ".env"
    if not env_path.exists():
        values = {name: secrets.token_urlsafe(32) for name in ("API_TOKEN", "POSTGRES_PASSWORD", "MQTT_BACKEND_PASSWORD")}
        private_write(env_path, "".join(f"{k}={v}\n" for k, v in values.items()).encode())
    elif os.name != "nt":
        env_path.chmod(0o600)
    values = dict(line.split("=", 1) for line in env_path.read_text(encoding="utf-8-sig").splitlines() if line and not line.startswith("#"))
    credential_path = runtime / "devices.json"
    credentials = json.loads(credential_path.read_text()) if credential_path.exists() else []
    for index in range(len(credentials), devices):
        credentials.append({"device_id": f"device-{index+1:04d}", "password": secrets.token_urlsafe(24)})
    private_write(credential_path, json.dumps(credentials, indent=2).encode())
    lines = [f"backend:{values['MQTT_BACKEND_PASSWORD']}"] + [f"{d['device_id']}:{d['password']}" for d in credentials]
    password_database(broker, lines)
    (broker / "acl").write_text("user backend\ntopic readwrite devices/#\n\npattern write devices/%u/telemetry\npattern write devices/%u/reported\npattern write devices/%u/sync\npattern read devices/%u/desired\npattern read devices/%u/receipt\n", encoding="utf-8")
    (broker / "mosquitto.conf").write_text("listener 8883\nallow_anonymous false\npassword_file /mosquitto/config/passwords\nacl_file /mosquitto/config/acl\ncafile /mosquitto/certs/ca.crt\ncertfile /mosquitto/certs/server.crt\nkeyfile /mosquitto/certs/server.key\npersistence true\npersistence_location /mosquitto/data/\nautosave_interval 30\nmax_queued_messages 10000\nmessage_size_limit 65536\nlog_dest stdout\n", encoding="utf-8")
    for name in ("acl", "mosquitto.conf"):
        service_readable(broker / name)
    return len(credentials)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.devices <= 10000:
        parser.error("devices must be between 1 and 10000")
    count = bootstrap(args.devices)
    print(f"Local credentials and CA ready for {count} devices. Secrets remain in .env and .runtime/.")
    print("Start services: docker compose up -d --build")


if __name__ == "__main__":
    main()
