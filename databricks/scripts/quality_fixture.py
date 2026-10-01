"""Write deterministic two-phase synthetic data for cloud recovery verification."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def event(sequence: int, minute: int, energy: float):
    timestamp = f"2026-01-01T00:{minute:02d}:00Z"
    return {"schema_version": 1, "event_id": str(uuid5(NAMESPACE_URL, f"appliance-cloud-quality-{sequence}")),
            "device_id": "quality-fixture", "boot_id": str(uuid5(NAMESPACE_URL, "appliance-cloud-quality-boot")),
            "sequence": sequence, "event_time": timestamp, "source_kind": "simulated",
            "power_w": 60.0, "energy_wh_total": energy, "firmware_version": "quality-fixture-v1",
            "quality_flags": [], "received_at": timestamp}


def write(output: Path):
    first, late, last = event(0, 0, 0.0), event(1, 5, 5.0), event(2, 10, 10.0)
    duplicate = deepcopy(last)
    duplicate["received_at"] = "2026-01-01T01:00:00Z"
    conflict = deepcopy(last)
    conflict["power_w"] = 999.0
    slot = deepcopy(late)
    slot["event_id"] = str(uuid5(NAMESPACE_URL, "appliance-cloud-quality-slot-conflict"))
    invalid = event(3, 15, 15.0)
    invalid["event_time"] = "badZ"
    output.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("phase-one.jsonl", [first, last]),
                           ("phase-two.jsonl", [late, duplicate, conflict, slot, invalid])):
        (output / filename).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    # Force a later conflicting file to sort before all original evidence.
    earlier_hash_conflict = deepcopy(last)
    earlier_hash_conflict["power_w"] = 1200.0
    threshold = min(hashlib.sha256((output / name).read_bytes()).hexdigest()
                    for name in ("phase-one.jsonl", "phase-two.jsonl"))
    for spaces in range(10000):
        content = (json.dumps(earlier_hash_conflict, sort_keys=True) + " " * spaces + "\n").encode()
        if hashlib.sha256(content).hexdigest() < threshold:
            (output / "earlier-hash-conflict.jsonl").write_bytes(content)
            break
    else:
        raise RuntimeError("Could not construct bounded source-order conflict fixture")
    expected = {
        "phase_one": {"accepted_events": 2, "covered_energy_wh": "0.00000000", "unallocated_energy_wh": "10.00000000"},
        "phase_two": {"accepted_events": 3, "covered_energy_wh": "10.00000000", "unallocated_energy_wh": "0.00000000"},
        "quality_cases": ["late sequence repairs gap", "delivery timestamp excluded from identity",
                          "conflicting event payload quarantined", "device boot sequence collision quarantined",
                          "malformed timestamp quarantined with ANSI mode enabled",
                          "later conflicting source hash sorts before accepted evidence"],
        "note": "Either equal-payload sequence-one identity can win when first encountered together; verify unique slots and energy.",
    }
    (output / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(expected, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    write(parser.parse_args().output)
