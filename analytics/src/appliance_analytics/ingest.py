"""Immutable raw evidence, identity checks and explicit interval accounting."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import UUID

import duckdb
import pandas as pd

KINDS = {"simulated", "measured", "estimated", "public_dataset"}
REQUIRED = {"schema_version", "event_id", "device_id", "boot_id", "sequence", "event_time", "source_kind", "power_w", "energy_wh_total", "firmware_version", "quality_flags", "received_at"}
SILVER_COLUMNS = ["schema_version", "event_id", "device_id", "boot_id", "sequence_no", "event_time", "received_at", "source_kind", "power_w", "energy_wh_total", "firmware_version", "quality_flags_json", "payload_hash"]
HOUR_COLUMNS = ["device_id", "source_kind", "hour", "energy_wh", "unallocated_energy_wh", "coverage_seconds", "reading_count", "mean_power_w", "peak_power_w", "gap_count", "reset_count", "invalid_interval_count", "labelled_normal", "labelled_anomaly"]


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone='UTC'")
    con.execute("""
        CREATE TABLE IF NOT EXISTS bronze_events (
          source_hash VARCHAR, source_file VARCHAR, row_number BIGINT, raw_json VARCHAR,
          PRIMARY KEY(source_hash,row_number));
        CREATE TABLE IF NOT EXISTS quarantine (
          quarantine_id VARCHAR PRIMARY KEY, source_hash VARCHAR, row_number BIGINT,
          event_id VARCHAR, reason VARCHAR, raw_json VARCHAR);
        CREATE TABLE IF NOT EXISTS silver_telemetry (
          schema_version INTEGER, event_id VARCHAR PRIMARY KEY, device_id VARCHAR,
          boot_id VARCHAR, sequence_no BIGINT, event_time TIMESTAMPTZ, received_at TIMESTAMPTZ,
          source_kind VARCHAR, power_w DOUBLE, energy_wh_total DOUBLE, firmware_version VARCHAR,
          quality_flags_json VARCHAR, payload_hash VARCHAR,
          UNIQUE(device_id,boot_id,sequence_no));
    """)
    return con


def utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("timestamp must include a UTC offset")
    return result.astimezone(timezone.utc)


def validate(event: dict) -> dict:
    if not isinstance(event, dict) or set(event) != REQUIRED:
        raise ValueError("event fields do not match normalized protocol v1")
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    if not isinstance(event["device_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", event["device_id"]):
        raise ValueError("invalid device_id")
    for field in ("event_id", "boot_id"):
        if not isinstance(event[field], str) or str(UUID(event[field])) != event[field].lower():
            raise ValueError(f"invalid {field}")
    if type(event["sequence"]) is not int or not 0 <= event["sequence"] <= 2**63 - 1:
        raise ValueError("invalid sequence")
    if event["source_kind"] not in KINDS:
        raise ValueError("invalid source_kind")
    for field in ("power_w", "energy_wh_total"):
        value = event[field]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid {field}")
    if not isinstance(event["firmware_version"], str) or not 1 <= len(event["firmware_version"]) <= 128:
        raise ValueError("invalid firmware_version")
    flags = event["quality_flags"]
    if not isinstance(flags, list) or len(flags) > 32 or any(not isinstance(x, str) or len(x) > 128 for x in flags):
        raise ValueError("invalid quality_flags")
    parsed = dict(event)
    parsed["event_id"] = str(UUID(event["event_id"]))
    parsed["boot_id"] = str(UUID(event["boot_id"]))
    parsed["event_time"] = utc(event["event_time"])
    parsed["received_at"] = utc(event["received_at"])
    # Delivery timestamps are transport metadata, not the immutable device payload.
    device_payload = {k: v for k, v in event.items() if k != "received_at"}
    device_payload["event_id"] = parsed["event_id"]
    device_payload["boot_id"] = parsed["boot_id"]
    device_payload["event_time"] = parsed["event_time"].isoformat()
    parsed["payload_hash"] = hashlib.sha256(json.dumps(device_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return parsed


def append_rows(con, table: str, columns: list[str], rows: list[tuple], deduplicate: bool = True) -> None:
    if rows:
        con.register("_incoming", pd.DataFrame(rows, columns=columns))
        conflict = " ON CONFLICT DO NOTHING" if deduplicate else ""
        con.execute(f"INSERT INTO {table} SELECT * FROM _incoming{conflict}")
        con.unregister("_incoming")


def ingest(con, paths: list[str | Path], max_gap_seconds: float = 120) -> dict:
    if not math.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError("max_gap_seconds must be positive")
    seen_ids = {}
    seen_slots = {}
    for event_id, device, boot, seq, payload_hash in con.execute("SELECT event_id, device_id, boot_id, sequence_no, payload_hash FROM silver_telemetry").fetchall():
        seen_ids[event_id] = payload_hash
        seen_slots[(device, boot, seq)] = (event_id, payload_hash)
    known_raw = set(con.execute("SELECT DISTINCT source_hash FROM bronze_events").fetchnumpy()["source_hash"])
    raw_rows, accepted, rejected = [], [], []
    counts = {"accepted": 0, "duplicates": 0, "quarantined": 0, "replayed_files": 0}
    for source in paths:
        path = Path(source)
        content = path.read_bytes()
        source_hash = hashlib.sha256(content).hexdigest()
        if source_hash in known_raw:
            counts["replayed_files"] += 1
            continue
        known_raw.add(source_hash)
        for number, raw in enumerate(content.decode("utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            raw_rows.append((source_hash, path.name, number, raw))
            event = {}
            try:
                event = json.loads(raw)
                parsed = validate(event)
                event_id, payload_hash = parsed["event_id"], parsed["payload_hash"]
                slot = (parsed["device_id"], parsed["boot_id"], parsed["sequence"])
                if event_id in seen_ids:
                    if seen_ids[event_id] != payload_hash:
                        raise ValueError("conflicting_event_id")
                    counts["duplicates"] += 1
                    continue
                if slot in seen_slots:
                    raise ValueError("conflicting_device_boot_sequence")
                seen_ids[event_id] = payload_hash
                seen_slots[slot] = (event_id, payload_hash)
                accepted.append(tuple(parsed[k] for k in ["schema_version", "event_id", "device_id", "boot_id", "sequence", "event_time", "received_at", "source_kind", "power_w", "energy_wh_total", "firmware_version"]) + (json.dumps(parsed["quality_flags"]), payload_hash))
                counts["accepted"] += 1
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                reason = str(exc)[:200]
                qid = hashlib.sha256(f"{source_hash}:{number}:{reason}".encode()).hexdigest()
                rejected.append((qid, source_hash, number, str(event.get("event_id", "")) if isinstance(event, dict) else "", reason, raw))
                counts["quarantined"] += 1
    con.execute("BEGIN TRANSACTION")
    try:
        append_rows(con, "bronze_events", ["source_hash", "source_file", "row_number", "raw_json"], raw_rows)
        append_rows(con, "silver_telemetry", SILVER_COLUMNS, accepted)
        append_rows(con, "quarantine", ["quarantine_id", "source_hash", "row_number", "event_id", "reason", "raw_json"], rejected)
        build_gold(con, max_gap_seconds)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return counts


def build_gold(con, max_gap_seconds: float) -> None:
    buckets = defaultdict(lambda: {"energy_wh": 0.0, "unallocated_energy_wh": 0.0, "coverage_seconds": 0.0, "reading_count": 0, "power_sum": 0.0, "peak_power_w": 0.0, "gap_count": 0, "reset_count": 0, "invalid_interval_count": 0, "labelled_normal": True, "labelled_anomaly": False})
    previous = {}
    query = "SELECT device_id, source_kind, boot_id, sequence_no, event_time, power_w, energy_wh_total, quality_flags_json FROM silver_telemetry ORDER BY device_id, source_kind, event_time, event_id"
    for device, kind, boot, seq, timestamp, power, counter, flags_json in con.execute(query).fetchall():
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        bucket = buckets[(device, kind, hour)]
        bucket["reading_count"] += 1
        bucket["power_sum"] += power
        bucket["peak_power_w"] = max(bucket["peak_power_w"], power)
        flags = json.loads(flags_json)
        bucket["labelled_anomaly"] |= "injected_anomaly" in flags
        bucket["labelled_normal"] &= "evaluation_label_normal" in flags
        key = (device, kind)
        prior = previous.get(key)
        if prior is None:
            previous[key] = (boot, seq, timestamp, counter)
            continue
        old_boot, old_seq, old_time, old_counter = prior
        if boot != old_boot:
            bucket["reset_count"] += 1
            previous[key] = (boot, seq, timestamp, counter)
            continue
        seconds = (timestamp - old_time).total_seconds()
        delta = counter - old_counter
        if seconds <= 0 or seq <= old_seq or delta < -1e-8:
            bucket["invalid_interval_count"] += 1
            continue
        # An invalid reading cannot become the next energy baseline. Otherwise a
        # temporary counter regression and recovery would invent consumed energy.
        previous[key] = (boot, seq, timestamp, counter)
        delta = max(0.0, delta)
        if seconds > max_gap_seconds or seq != old_seq + 1:
            # Counter delta is known; its missing-interval distribution is not.
            bucket["gap_count"] += 1
            bucket["unallocated_energy_wh"] += delta
            continue
        cursor = old_time
        while cursor < timestamp:
            interval_hour = cursor.replace(minute=0, second=0, microsecond=0)
            end = min(interval_hour + timedelta(hours=1), timestamp)
            overlap = (end - cursor).total_seconds()
            contribution = buckets[(device, kind, interval_hour)]
            contribution["energy_wh"] += delta * overlap / seconds
            contribution["coverage_seconds"] += overlap
            cursor = end
    hourly = []
    for (device, kind, hour), b in sorted(buckets.items()):
        mean = b["power_sum"] / b["reading_count"] if b["reading_count"] else None
        hourly.append((device, kind, hour, b["energy_wh"], b["unallocated_energy_wh"], b["coverage_seconds"], b["reading_count"], mean, b["peak_power_w"], b["gap_count"], b["reset_count"], b["invalid_interval_count"], b["labelled_normal"], b["labelled_anomaly"]))
    con.execute("""CREATE OR REPLACE TABLE gold_device_hourly (
      device_id VARCHAR, source_kind VARCHAR, hour TIMESTAMPTZ, energy_wh DECIMAL(24,8),
      unallocated_energy_wh DECIMAL(24,8), coverage_seconds DOUBLE, reading_count BIGINT,
      mean_power_w DOUBLE, peak_power_w DOUBLE, gap_count BIGINT, reset_count BIGINT,
      invalid_interval_count BIGINT, labelled_normal BOOLEAN, labelled_anomaly BOOLEAN)""")
    append_rows(con, "gold_device_hourly", HOUR_COLUMNS, hourly, deduplicate=False)
    con.execute("""CREATE OR REPLACE TABLE gold_device_daily AS SELECT
      device_id, source_kind, CAST(hour AS DATE) AS day,
      sum(energy_wh) AS energy_wh, sum(unallocated_energy_wh) AS unallocated_energy_wh,
      sum(coverage_seconds) AS coverage_seconds, least(1.0,sum(coverage_seconds)/86400.0) AS coverage_ratio,
      sum(reading_count)::BIGINT AS reading_count,
      sum(mean_power_w*reading_count)/nullif(sum(reading_count),0) AS mean_power_w,
      max(peak_power_w) AS peak_power_w, sum(gap_count)::BIGINT AS gap_count,
      sum(reset_count)::BIGINT AS reset_count, sum(invalid_interval_count)::BIGINT AS invalid_interval_count,
      CASE WHEN bool_or(labelled_anomaly) THEN true WHEN bool_and(labelled_normal) AND sum(reading_count)>0 THEN false ELSE NULL END AS injected_anomaly_label
      FROM gold_device_hourly GROUP BY device_id, source_kind, CAST(hour AS DATE);
      CREATE OR REPLACE TABLE gold_quality AS SELECT
      (SELECT count(*) FROM bronze_events)::BIGINT AS bronze_rows,
      (SELECT count(*) FROM silver_telemetry)::BIGINT AS accepted_events,
      (SELECT count(*) FROM quarantine)::BIGINT AS quarantined_rows,
      coalesce(sum(gap_count),0)::BIGINT AS gap_count,
      coalesce(sum(invalid_interval_count),0)::BIGINT AS invalid_interval_count,
      coalesce(sum(unallocated_energy_wh),0) AS unallocated_energy_wh
      FROM gold_device_daily;
    """)
