"""Exercise the real HTTP, TLS MQTT, device and database path.

Run through with_env.py after docker compose is healthy. Results contain no tokens.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from appliance_simulator.device import Device

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for expected integration outcome")


def main():
    api_url = os.environ.get("API_URL", "http://127.0.0.1:18080")
    checks = []
    credentials = json.loads((ROOT / ".runtime/devices.json").read_text())
    credential = credentials[0]
    device_id = credential["device_id"]
    start = time.monotonic()
    with httpx.Client(base_url=api_url, headers={"Authorization": f"Bearer {os.environ['API_TOKEN']}"}, timeout=10) as api:
        assert httpx.get(api_url + "/api/devices").status_code in (401, 403)
        checks.append("unauthenticated API rejected")
        response = api.post("/api/devices", json={"device_id": device_id, "name": device_id})
        assert response.status_code in (200, 201)
        with tempfile.TemporaryDirectory(prefix="appliance-smoke-") as temporary:
            device = Device(device_id, credential["password"], "127.0.0.1", 18883,
                            ROOT / ".runtime/certs/ca.crt", Path(temporary), interval=0.5)
            device.start()
            try:
                wait_for(lambda: device.connected.is_set())
                current = api.get(f"/api/devices/{device_id}").json()
                command = {"command_id": str(uuid.uuid4()), "expected_revision": current["desired_revision"],
                           "desired": {"power": True, "speed_percent": 37},
                           "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()}
                first = api.post(f"/api/devices/{device_id}/commands", json=command)
                assert first.status_code in (200, 201, 202), first.text
                receipt = first.json()
                for _ in range(10):
                    duplicate = api.post(f"/api/devices/{device_id}/commands", json=command)
                    assert duplicate.status_code in (200, 201, 202), duplicate.text
                    assert duplicate.json()["revision"] == receipt["revision"]
                    assert duplicate.json()["command_id"] == command["command_id"]
                checks.append("ten API retries preserve one command and revision")
                changed = dict(command, desired={"power": False, "speed_percent": 0})
                assert api.post(f"/api/devices/{device_id}/commands", json=changed).status_code == 409
                stale = dict(command, command_id=str(uuid.uuid4()))
                assert api.post(f"/api/devices/{device_id}/commands", json=stale).status_code == 409
                checks.append("changed payload and stale revision rejected")
                wait_for(lambda: api.get(f"/api/commands/{command['command_id']}").json()["status"] == "confirmed")
                checks.append("real TLS MQTT report confirms desired state")
                telemetry = device.state.sample(10)
                device.publish("telemetry", telemetry)
                wait_for(lambda: device.state.stats()["accepted"] == 1)
                device.publish("telemetry", telemetry)
                time.sleep(0.5)
                readings = api.get(f"/api/devices/{device_id}/telemetry", params={"limit": 1000}).json()
                assert sum(row["event_id"] == telemetry["event_id"] for row in readings) == 1
                checks.append("telemetry duplicate has one durable logical row and receipt")
                device.drop_reports = True
                second = {"command_id": str(uuid.uuid4()), "expected_revision": receipt["revision"],
                          "desired": {"power": False, "speed_percent": 0}, "expires_at": command["expires_at"]}
                reply = api.post(f"/api/devices/{device_id}/commands", json=second)
                assert reply.status_code in (200, 201, 202), reply.text
                wait_for(lambda: device.state.snapshot()["revision"] == reply.json()["revision"])
                time.sleep(0.5)
                assert api.get(f"/api/commands/{second['command_id']}").json()["status"] != "confirmed"
                device.drop_reports = False
                device.report()
                wait_for(lambda: api.get(f"/api/commands/{second['command_id']}").json()["status"] == "confirmed")
                checks.append("lost application report remains unconfirmed until reconciled")
                expired = dict(second, command_id=str(uuid.uuid4()), expected_revision=reply.json()["revision"], expires_at="2020-01-01T00:00:00Z")
                assert api.post(f"/api/devices/{device_id}/commands", json=expired).status_code == 400
                checks.append("expired command rejected")
            finally:
                device.stop()
    result = {"status": "passed", "checks": checks, "duration_seconds": round(time.monotonic()-start, 3),
              "environment": "local Docker PostgreSQL, Java, Mosquitto TLS and Python simulator"}
    output = ROOT / "artifacts/integration-smoke.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
