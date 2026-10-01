"""Bounded acceptance on a fresh temporary Linux host; produces no credentials."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def execute(*args, timeout=450):
    subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def read_batches(path):
    rows = {}
    physical = 0
    manifests = list(path.glob("*/manifest.json"))
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        raw = (manifest_path.parent / "events.jsonl").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == manifest["sha256"]
        events = [json.loads(line) for line in raw.splitlines() if line]
        assert len(events) == manifest["row_count"]
        for event in events:
            key = event["event_id"]
            if key in rows:
                assert rows[key] == event, "changed event identity in Kafka export"
            rows[key] = event
        physical += len(events)
    assert rows, "empty export is not successful transport evidence"
    return rows, {"manifests": len(manifests), "physical_rows": physical, "unique_events": len(rows)}


def package_diagnostics(artifacts):
    """Inventory shipped migrations without publishing application binaries."""
    with tempfile.TemporaryDirectory(prefix="azure-package-") as directory:
        jar = Path(directory) / "app.jar"
        execute("docker", "compose", "cp", "backend:/app/app.jar", str(jar), timeout=30)
        with zipfile.ZipFile(jar) as package:
            names = package.namelist()
            resources = {name: hashlib.sha256(package.read(name)).hexdigest()
                         for name in names if name.startswith("BOOT-INF/classes/db/") and not name.endswith("/")}
            inventory = {"application_jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
                         "migration_entries": [name for name in names if "/db/" in name],
                         "migration_sha256": resources,
                         "flyway_dependencies": [name for name in names if "/flyway-" in name],
                         "configuration_entries": [name for name in names if name.endswith("application.yml")]}
        (artifacts / "azure-package.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")


def main():
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key] = value
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    started = time.monotonic()
    samples = []
    stopped = threading.Event()

    def monitor():
        while not stopped.is_set():
            try:
                stat = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                                      cwd=ROOT, check=True, capture_output=True, text=True, timeout=15)
                samples.append({"elapsed_seconds": round(time.monotonic() - started, 2),
                                "containers": [json.loads(row) for row in stat.stdout.splitlines()]})
            except (subprocess.SubprocessError, ValueError) as exc:
                samples.append({"monitor_error": type(exc).__name__})
            stopped.wait(10)

    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()
    try:
        ready_deadline = time.monotonic() + 120
        while True:
            try:
                ready = httpx.get("http://127.0.0.1:18080/actuator/health", timeout=5)
                if ready.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= ready_deadline:
                raise TimeoutError("backend did not become healthy")
            time.sleep(2)
        package_diagnostics(artifacts)
        package = json.loads((artifacts / "azure-package.json").read_text())
        assert "BOOT-INF/classes/db/migration/V1__initial.sql" in package["migration_entries"]
        # Keep first-request diagnostics: a readiness endpoint alone does not
        # prove authentication, request mapping or database writes work.
        credential = json.loads((ROOT / ".runtime/devices.json").read_text())[0]
        with httpx.Client(base_url="http://127.0.0.1:18080", timeout=30,
                          headers={"Authorization": "Bearer " + os.environ["API_TOKEN"]}) as client:
            response = client.post("/api/devices", json={"device_id": credential["device_id"],
                                                       "name": credential["device_id"]})
            if response.status_code not in (200, 201):
                raise RuntimeError(f"initial registration HTTP {response.status_code}: {response.text[:2000]}")
        execute(sys.executable, "scripts/smoke.py")
        transport = json.loads((artifacts / "integration-smoke.json").read_text())
        transport["environment"] = "Azure temporary Linux VM: Docker PostgreSQL, Java, Kafka, Mosquitto TLS; simulated devices"
        (artifacts / "integration-smoke.json").write_text(json.dumps(transport, indent=2))
        execute(sys.executable, "-m", "appliance_simulator.cli", "run", "--count", "100", "--interval", "10",
                "--duration", "300", "--drain-seconds", "60", "--stats", "artifacts/azure-fleet.json")
        fleet = json.loads((artifacts / "azure-fleet.json").read_text())
        accepted = sum(value["accepted"] - fleet["initial_device_counters"][key]["accepted"]
                       for key, value in fleet["devices"].items())
        dropped = sum(value["dropped"] - fleet["initial_device_counters"][key]["dropped"]
                      for key, value in fleet["devices"].items())
        pending = sum(value["pending"] for value in fleet["devices"].values())
        assert accepted == fleet["generated_events"] and dropped == pending == 0
        for group in ("azure-export-original", "azure-export-replay"):
            execute(sys.executable, "-m", "appliance_simulator.cli", "export", "--once", "--group", group,
                    "--output", f"data/{group}", timeout=120)
        first, first_summary = read_batches(ROOT / "data/azure-export-original")
        replay, replay_summary = read_batches(ROOT / "data/azure-export-replay")
        assert first == replay, "new Kafka consumer group changed the logical export"
        with httpx.Client(base_url="http://127.0.0.1:18080", timeout=30,
                          headers={"Authorization": "Bearer " + os.environ["API_TOKEN"]}) as client:
            api_ids = set()
            for credential in json.loads((ROOT / ".runtime/devices.json").read_text()):
                response = client.get(f"/api/devices/{credential['device_id']}/telemetry", params={"limit": 1000})
                response.raise_for_status()
                api_ids.update(row["event_id"] for row in response.json())
            assert api_ids == set(first), "PostgreSQL/API and Kafka export disagree"
        result = {
            "status": "passed", "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(), "environment": transport["environment"],
            "transport": transport, "fleet": {k: v for k, v in fleet.items()
                                                if k not in ("devices", "initial_device_counters")},
            "accepted_delta": accepted, "dropped_delta": dropped, "pending_at_end": pending,
            "original_export": first_summary, "replay_export": replay_summary,
            "kafka_replay_identical": True, "api_unique_events": len(api_ids),
            "api_kafka_identity_reconciliation": True,
            "duration_seconds": round(time.monotonic() - started, 3),
            "limitations": ["Single short shared-host run; not a capacity or availability SLA.",
                            "Devices are software simulations; no physical appliance was tested.",
                            "This run validates Azure VM/Compose runtime, not AKS or IoT Hub."]}
        (artifacts / "azure-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    except BaseException:
        diagnostic = subprocess.run(["docker", "compose", "logs", "--tail", "1000", "backend"],
                                    cwd=ROOT, capture_output=True, text=True, timeout=20)
        print("Backend failure diagnostics:\n" + diagnostic.stdout + diagnostic.stderr, flush=True)
        try:
            package_diagnostics(artifacts)
        except Exception as error:
            print("Package diagnostic failure: " + str(error), flush=True)
        raise
    finally:
        stopped.set()
        worker.join(timeout=20)
        (artifacts / "azure-container-samples.json").write_text(json.dumps(samples, indent=2) + "\n")


if __name__ == "__main__":
    main()
