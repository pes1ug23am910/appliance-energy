from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must have an explicit timezone")
    return result.astimezone(timezone.utc)


class DeviceState:
    """Durable desired state and bounded telemetry awaiting ingestion receipts.

    Process restart creates a new metering epoch. Pending events from previous
    epochs survive and retain their original identities.
    """

    def __init__(self, path: Path, device_id: str, capacity: int = 10000):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.device_id = device_id
        self.capacity = capacity
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS pending (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
          INSERT OR IGNORE INTO counters VALUES ('dropped',0);
          INSERT OR IGNORE INTO counters VALUES ('accepted',0);
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO settings VALUES(1,?)", (json.dumps({"revision": 0, "power": False, "speed_percent": 0, "command_id": None}),))
        self.boot_id = str(uuid.uuid4())
        self.sequence = 0
        self.report_sequence = 0
        self.energy_wh = 0.0

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(self.db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])

    def apply(self, command: dict, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        if command.get("device_id") != self.device_id:
            return "wrong_device"
        desired = command.get("desired", {})
        if type(desired.get("power")) is not bool or type(desired.get("speed_percent")) is not int:
            return "invalid"
        if not 0 <= desired["speed_percent"] <= 100 or type(command.get("revision")) is not int:
            return "invalid"
        try:
            if parse_time(command["expires_at"]) <= now:
                return "expired"
            uuid.UUID(command["command_id"])
        except (KeyError, ValueError, TypeError):
            return "invalid"
        with self.lock, self.db:
            current = self.snapshot()
            revision = command["revision"]
            if revision < current["revision"]:
                return "stale"
            if revision == current["revision"]:
                if all(current[k] == desired[k] for k in ("power", "speed_percent")) and current["command_id"] == command["command_id"]:
                    return "duplicate"
                return "conflict"
            new = dict(desired, revision=revision, command_id=command["command_id"])
            self.db.execute("UPDATE settings SET value=? WHERE id=1", (json.dumps(new, sort_keys=True),))
        return "applied"

    def report(self) -> dict:
        with self.lock:
            self.report_sequence += 1
            state = self.snapshot()
            result = dict(state, device_id=self.device_id, boot_id=self.boot_id,
                          sequence=self.report_sequence, observed_at=utcnow(), firmware_version="sim-1.0.0")
        if result["command_id"] is None:
            del result["command_id"]
        return result

    def sample(self, elapsed_seconds: float) -> dict | None:
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be finite and nonnegative")
        with self.lock, self.db:
            state = self.snapshot()
            self.sequence += 1
            power = 2.0 + (40.0 * state["speed_percent"] / 100 if state["power"] else 0.0)
            self.energy_wh += power * elapsed_seconds / 3600
            count = self.db.execute("SELECT count(*) FROM pending").fetchone()[0]
            if count >= self.capacity:
                self.db.execute("UPDATE counters SET value=value+1 WHERE name='dropped'")
                return None
            event = dict(schema_version=1, event_id=str(uuid.uuid4()), device_id=self.device_id,
                         boot_id=self.boot_id, sequence=self.sequence, event_time=utcnow(),
                         source_kind="simulated", power_w=power, energy_wh_total=self.energy_wh,
                         firmware_version="sim-1.0.0", quality_flags=[])
            self.db.execute("INSERT INTO pending VALUES(?,?)", (event["event_id"], json.dumps(event, sort_keys=True)))
            return event

    def pending(self, limit: int = 100) -> list[dict]:
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM pending ORDER BY rowid LIMIT ?", (limit,))]

    def acknowledge(self, event_id: str) -> None:
        with self.lock, self.db:
            deleted = self.db.execute("DELETE FROM pending WHERE event_id=?", (event_id,)).rowcount
            self.db.execute("UPDATE counters SET value=value+? WHERE name='accepted'", (deleted,))

    def stats(self) -> dict:
        with self.lock:
            stats = dict(self.db.execute("SELECT name,value FROM counters"))
            stats["pending"] = self.db.execute("SELECT count(*) FROM pending").fetchone()[0]
            return stats

    def close(self) -> None:
        self.db.close()
