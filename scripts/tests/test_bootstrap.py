"""Clean-clone credential and file-permission regressions; no live services."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("bootstrap", Path(__file__).resolve().parents[1] / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fake_hasher(self, command, *, check):
        self.assertTrue(check)
        self.assertEqual("0" if os.name == "nt" else f"{os.getuid()}:{os.getgid()}", command[command.index("--user") + 1])
        stage = Path(command[command.index("-v") + 1].removesuffix(":/work"))
        rows = (stage / "passwords").read_text().splitlines()
        self.assertTrue(all(row.split(":", 1)[1] not in command for row in rows))
        (stage / "passwords").write_text("\n".join(row.split(":", 1)[0] + ":$7$test-hash" for row in rows) + "\n")

    def test_bootstrap_preserves_identity_while_adding_devices_and_excludes_ca_key_from_mount(self):
        with patch.object(bootstrap.subprocess, "run", side_effect=self.fake_hasher):
            self.assertEqual(2, bootstrap.bootstrap(2, self.root))
            credentials = json.loads((self.root / ".runtime/devices.json").read_text())
            certificate = (self.root / ".runtime/certs/server.crt").read_bytes()
            environment = (self.root / ".env").read_bytes()
            self.assertEqual(3, bootstrap.bootstrap(3, self.root))
        self.assertEqual(credentials, json.loads((self.root / ".runtime/devices.json").read_text())[:2])
        self.assertEqual(certificate, (self.root / ".runtime/certs/server.crt").read_bytes())
        self.assertEqual(environment, (self.root / ".env").read_bytes())
        self.assertTrue((self.root / ".runtime/private/ca.key").is_file())
        self.assertFalse((self.root / ".runtime/certs/ca.key").exists())

    @unittest.skipIf(os.name == "nt", "POSIX modes need a Linux filesystem")
    def test_restrictive_umask_keeps_host_secrets_private_and_service_mounts_readable(self):
        previous = os.umask(0o077)
        try:
            with patch.object(bootstrap.subprocess, "run", side_effect=self.fake_hasher):
                bootstrap.bootstrap(1, self.root)
        finally:
            os.umask(previous)
        for name in (".env", ".runtime/devices.json", ".runtime/private/ca.key"):
            self.assertEqual(0o600, stat.S_IMODE((self.root / name).stat().st_mode), name)
        self.assertEqual(0o700, stat.S_IMODE((self.root / ".runtime").stat().st_mode))
        for name in (".runtime/certs", ".runtime/mosquitto"):
            self.assertEqual(0o755, stat.S_IMODE((self.root / name).stat().st_mode), name)
        for name in ("certs/ca.crt", "certs/server.crt", "certs/server.key", "mosquitto/acl", "mosquitto/mosquitto.conf", "mosquitto/passwords"):
            self.assertEqual(0o644, stat.S_IMODE((self.root / ".runtime" / name).stat().st_mode), name)

    def test_hash_failure_leaves_active_database_unchanged_and_cleans_plaintext_stage(self):
        broker = self.root / "broker"
        broker.mkdir()
        (broker / "passwords").write_text("old-hashed-contents")
        with patch.object(bootstrap.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "docker")):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.password_database(broker, ["backend:temporary-secret"])
        self.assertEqual("old-hashed-contents", (broker / "passwords").read_text())
        self.assertEqual(["passwords"], [path.name for path in broker.iterdir()])

    def test_legacy_ca_key_moves_without_changing_issued_certificates(self):
        certs, private = self.root / "certs", self.root / "private"
        bootstrap.certificates(certs, private)
        key = (private / "ca.key").read_bytes()
        cert = (certs / "server.crt").read_bytes()
        (private / "ca.key").replace(certs / "ca.key")
        bootstrap.certificates(certs, private)
        self.assertEqual(key, (private / "ca.key").read_bytes())
        self.assertEqual(cert, (certs / "server.crt").read_bytes())
        self.assertFalse((certs / "ca.key").exists())

    def test_partial_certificate_directory_fails_without_rotating_trust(self):
        certs = self.root / "certs"
        certs.mkdir()
        (certs / "ca.crt").write_text("existing-trust-anchor")
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            bootstrap.certificates(certs, self.root / "private")
        self.assertEqual("existing-trust-anchor", (certs / "ca.crt").read_text())


if __name__ == "__main__":
    unittest.main()
