from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import statistics
import threading
import time
from pathlib import Path

import httpx

from .device import Device
from .export import consume


def main():
    parser = argparse.ArgumentParser(description="Appliance simulator and durable telemetry exporter")
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    run.add_argument("--credentials", type=Path, default=Path(".runtime/devices.json"))
    run.add_argument("--ca", type=Path, default=Path(".runtime/certs/ca.crt"))
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=18883)
    run.add_argument("--api", default="http://127.0.0.1:18080")
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--start-index", type=int, default=0, help="zero-based credential offset")
    run.add_argument("--interval", type=float, default=10)
    run.add_argument("--duration", type=float, default=0, help="seconds; 0 until interrupted")
    run.add_argument("--drain-seconds", type=float, default=10, help="receipt drain window after generation ends")
    run.add_argument("--state-dir", type=Path, default=Path(".runtime/simulator"))
    run.add_argument("--drop-reports", action="store_true")
    run.add_argument("--stats", type=Path, default=Path("artifacts/simulator-stats.json"))
    exp = sub.add_parser("export")
    exp.add_argument("--bootstrap", default="127.0.0.1:19092")
    exp.add_argument("--topic", default="appliance.telemetry.v1")
    exp.add_argument("--group", default="appliance-file-export-v1")
    exp.add_argument("--output", type=Path, default=Path("data/batches"))
    exp.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("kafka").setLevel(logging.WARNING)
    if args.action == "export":
        consume(args.bootstrap, args.topic, args.group, args.output, args.once)
        return
    if args.interval <= 0 or args.count < 1 or args.duration < 0 or args.start_index < 0 or args.drain_seconds < 0:
        parser.error("count and interval must be positive; duration cannot be negative")
    credentials = json.loads(args.credentials.read_text(encoding="utf-8-sig"))
    if args.start_index + args.count > len(credentials):
        parser.error("not enough provisioned credentials; rerun bootstrap with a larger device count")
    token = os.environ.get("API_TOKEN")
    if not token:
        parser.error("API_TOKEN must be set in the environment")
    devices = []
    initial = {}
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    with httpx.Client(base_url=args.api, headers={"Authorization": f"Bearer {token}"}, timeout=30) as api:
        for credential in credentials[args.start_index:args.start_index + args.count]:
            response = api.post("/api/devices", json={"device_id": credential["device_id"], "name": credential["device_id"]})
            if response.status_code not in (200, 201, 409):
                response.raise_for_status()
            device = Device(credential["device_id"], credential["password"], args.host, args.port,
                            args.ca, args.state_dir, args.interval, args.drop_reports)
            initial[device.device_id] = device.state.stats()
            device.start()
            devices.append(device)
    started = previous = time.monotonic()
    cpu_started = time.process_time()
    ticks = 0
    missed_ticks = 0
    try:
        while not stopped.wait(max(0, args.interval - (time.monotonic() - previous))):
            now = time.monotonic()
            elapsed = now - previous
            missed_ticks += max(0, int(elapsed / args.interval) - 1)
            for device in devices:
                device.tick(elapsed)
            ticks += 1
            previous = now
            if args.duration and now - started >= args.duration:
                break
        # Allow final application receipts to arrive before recording the backlog.
        drain_start = time.monotonic()
        while not stopped.is_set() and time.monotonic() - drain_start < args.drain_seconds:
            if all(d.state.stats()["pending"] == 0 for d in devices):
                break
            stopped.wait(0.2)
    finally:
        elapsed = time.monotonic() - started
        latencies = sorted(value for device in devices for value in list(device.receipt_seconds))
        delivery = {"sample_count": len(latencies), "definition": "first publish attempt to durable application receipt; bounded latest samples per device"}
        if latencies:
            delivery.update(p50_seconds=statistics.median(latencies),
                            p95_seconds=latencies[min(len(latencies)-1, int(.95*len(latencies)))],
                            max_seconds=max(latencies))
        stats = {"device_count": len(devices), "duration_seconds": elapsed,
                 "process_cpu_seconds": time.process_time() - cpu_started,
                 "interval_seconds": args.interval, "scheduled_ticks": ticks,
                 "missed_ticks": missed_ticks, "generated_events": ticks * len(devices),
                 "initial_device_counters": initial,
                 "receipt_latency": delivery,
                 "devices": {d.device_id: d.state.stats() for d in devices}}
        args.stats.parent.mkdir(parents=True, exist_ok=True)
        args.stats.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        for device in devices:
            device.stop()
        print(json.dumps({k: v for k, v in stats.items() if k not in ("devices", "initial_device_counters")}), flush=True)


if __name__ == "__main__":
    main()
