"""Deterministic synthetic fixtures and attributed REFIT power adaptation."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from urllib.request import urlopen

REFIT_URL = "https://zenodo.org/records/5063428/files/CLEAN_House1.csv?download=1"


def fixture(output: str | Path, days: int = 70, devices: int = 2) -> dict:
    if not 1 <= days <= 365 or not 1 <= devices <= 20:
        raise ValueError("fixture requires 1..365 days and 1..20 devices")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for device_number in range(devices):
            device = f"fixture-{device_number+1}"
            boot = str(uuid5(NAMESPACE_URL, device + ":boot:v1"))
            energy = 0.0
            previous_power = 0.0
            for sequence in range(days * 288 + 1):
                timestamp = start + timedelta(minutes=5 * sequence)
                day = sequence // 288
                hour = timestamp.hour + timestamp.minute / 60
                # Deterministic seasonality/trend; explicit injected anomalies only.
                anomaly = day in (40, 58, 65)
                base = 55 + 8 * device_number + 5 * (timestamp.weekday() >= 5) + 0.05 * day
                power = (base + 12 * math.sin(2 * math.pi * hour / 24) + 2 * math.sin(sequence * 0.73)) * (2.4 if anomaly else 1)
                if sequence:
                    energy += previous_power * 5 / 60
                previous_power = power
                event = {"schema_version": 1, "event_id": str(uuid5(NAMESPACE_URL, f"{device}:{sequence}:v1")), "device_id": device, "boot_id": boot, "sequence": sequence, "event_time": timestamp.isoformat(), "source_kind": "simulated", "power_w": round(power, 6), "energy_wh_total": round(energy, 8), "firmware_version": "fixture-1", "quality_flags": ["injected_anomaly" if anomaly else "evaluation_label_normal"], "received_at": timestamp.isoformat()}
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
                count += 1
    return {"rows": count, "path": str(path), "source_kind": "simulated", "sample_interval_seconds": 300, "recommended_max_gap_seconds": 600, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fetch_refit_sample(output: str | Path, rows: int = 1000) -> dict:
    if not 1 <= rows <= 10000:
        raise ValueError("public sample limited to 1..10000 rows")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with urlopen(REFIT_URL, timeout=30) as response, path.open("wb") as target:
        for index in range(rows + 1):
            line = response.readline(65537)
            if not line:
                break
            total += len(line)
            if len(line) > 65536 or total > 4_000_000:
                raise ValueError("sample exceeds bounded transfer size")
            target.write(line)
    provenance = {"source_url": REFIT_URL, "dataset_record": "https://zenodo.org/records/5063428", "raw_dataset_record": "https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/", "license": "CC BY 4.0 (raw dataset source)", "attribution": "Murray, D.; Stankovic, L.; Stankovic, V. REFIT Electrical Load Measurements. Cite doi:10.1038/sdata.2016.122.", "sample_rows_requested": rows, "bytes": total, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path.with_suffix(path.suffix + ".provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return provenance


def refit_adapt(source: str | Path, output: str | Path, power_column: str = "Aggregate", max_rows: int = 10000, device_id: str = "refit-house1") -> dict:
    if not 1 <= max_rows <= 100000:
        raise ValueError("max_rows must be 1..100000")
    path, target = Path(source), Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    previous = None
    boot = None
    sequence = 0
    energy = 0.0
    written = 0
    rejected = 0
    with path.open(encoding="utf-8-sig", newline="") as handle, target.open("w", encoding="utf-8", newline="\n") as sink:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or power_column not in reader.fieldnames or "Unix" not in reader.fieldnames:
            raise ValueError("REFIT CSV requires Unix and selected power column")
        for ordinal, row in enumerate(reader):
            if ordinal >= max_rows:
                break
            try:
                timestamp = datetime.fromtimestamp(float(row["Unix"]), timezone.utc)
                power = float(row[power_column])
                if not math.isfinite(power) or power < 0:
                    raise ValueError("invalid power")
            except (ValueError, OverflowError):
                rejected += 1
                previous = None
                continue
            seconds = (timestamp - previous[0]).total_seconds() if previous else 0
            if previous is None or not 0 < seconds <= 16:
                boot = str(uuid5(NAMESPACE_URL, f"{source_hash}:{power_column}:segment:{ordinal}"))
                sequence, energy = 0, 0.0
            else:
                # Left-held integration is an estimate; never call this a meter counter.
                energy += previous[1] * seconds / 3600
                sequence += 1
            event = {"schema_version": 1, "event_id": str(uuid5(NAMESPACE_URL, f"{source_hash}:{power_column}:{ordinal}")), "device_id": device_id, "boot_id": boot, "sequence": sequence, "event_time": timestamp.isoformat(), "source_kind": "public_dataset", "power_w": power, "energy_wh_total": energy, "firmware_version": "refit-adapter-1", "quality_flags": ["energy_counter_estimated_from_power", "refit_cc_by_4_attribution_required"], "received_at": timestamp.isoformat()}
            sink.write(json.dumps(event, separators=(",", ":")) + "\n")
            previous = (timestamp, power)
            written += 1
    report = {"rows": written, "invalid_rows_skipped": rejected, "source_file": path.name, "source_sha256": source_hash, "dataset_record": "https://zenodo.org/records/5063428", "power_column": power_column, "source_kind": "public_dataset", "energy_method": "left-held integration; segment reset on gaps >16 seconds or nonmonotonic time", "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    target.with_suffix(target.suffix + ".provenance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
