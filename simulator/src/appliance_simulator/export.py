from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def publish_batch(records: list, output: Path) -> Path | None:
    """Publish data and manifest atomically, then allow the caller to commit offsets."""
    if not records:
        return None
    output.mkdir(parents=True, exist_ok=True)
    events = [r.value if isinstance(r.value, dict) else json.loads(r.value) for r in records]
    raw = ("\n".join(json.dumps(e, sort_keys=True, separators=(",", ":")) for e in events) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    destination = output / digest
    if destination.exists():
        # A replay is safe only if both previously published artifacts are intact.
        saved = (destination / "events.jsonl").read_bytes()
        manifest = json.loads((destination / "manifest.json").read_text())
        if hashlib.sha256(saved).hexdigest() != digest or manifest["sha256"] != digest:
            raise ValueError("existing batch failed integrity verification")
        return destination
    manifest = {"schema_version": 1, "sha256": digest, "row_count": len(events),
                "event_ids_sha256": hashlib.sha256("\n".join(e["event_id"] for e in events).encode()).hexdigest(),
                "event_time_min": min(e["event_time"] for e in events),
                "event_time_max": max(e["event_time"] for e in events),
                "offsets": [{"topic": r.topic, "partition": r.partition, "offset": r.offset} for r in records]}
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=output))
    try:
        for filename, content in (("events.jsonl", raw), ("manifest.json", json.dumps(manifest, indent=2).encode())):
            with (staging / filename).open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        staging.rename(destination)
        # On POSIX persist the directory entry before advancing the Kafka cursor.
        if os.name != "nt":
            descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if staging.exists():
            for item in staging.iterdir():
                item.unlink()
            staging.rmdir()
    return destination


def consume(bootstrap: str, topic: str, group: str, output: Path, once: bool = False):
    from kafka import KafkaConsumer
    consumer = KafkaConsumer(topic, bootstrap_servers=bootstrap, group_id=group,
                             enable_auto_commit=False, auto_offset_reset="earliest",
                             api_version_auto_timeout_ms=15000,
                             max_poll_records=500, value_deserializer=lambda value: json.loads(value))
    try:
        idle_polls = 0
        started = time.monotonic()
        while True:
            batches = consumer.poll(timeout_ms=3000)
            records = [record for partition in sorted(batches, key=lambda p: (p.topic, p.partition)) for record in batches[partition]]
            if records:
                idle_polls = 0
                destination = publish_batch(records, output)
                consumer.commit()
                print(json.dumps({"batch": str(destination), "rows": len(records)}), flush=True)
            elif once:
                # Initial group assignment can produce empty polls before any
                # partition is readable; that is not evidence of a drained log.
                if consumer.assignment():
                    idle_polls += 1
                    if idle_polls >= 3:
                        break
                elif time.monotonic() - started > 60:
                    raise TimeoutError("Kafka assigned no partitions within 60 seconds")
    finally:
        consumer.close()
