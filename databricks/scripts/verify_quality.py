"""Assert two-phase cloud gap repair and immutable-identity quarantine results."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from verify_cloud import Workspace, compare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="databricks")
    parser.add_argument("--profile", default="appliance-energy")
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="appliance_energy_checks")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--fixture-folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in (args.catalog, args.schema)):
        raise ValueError("Invalid SQL identifier")
    before, after = (json.loads(path.read_text(encoding="utf-8")) for path in (args.before, args.after))
    assert before["identity"][0]["accepted_events"] == "2"
    assert Decimal(before["energy"][0]["energy_wh"]) == 0
    assert Decimal(before["energy"][0]["unallocated_energy_wh"]) == 10
    assert all(after["identity"][0][key] == "3" for key in ("accepted_events", "distinct_events", "distinct_slots"))
    assert Decimal(after["energy"][0]["energy_wh"]) == 10
    assert Decimal(after["energy"][0]["unallocated_energy_wh"]) == 0
    assert Decimal(after["energy"][0]["coverage_seconds"]) == 600
    hashes = {name: hashlib.sha256((args.fixture_folder / name).read_bytes()).hexdigest()
              for name in ("phase-one.jsonl", "phase-two.jsonl", "earlier-hash-conflict.jsonl")}
    assert hashes["earlier-hash-conflict.jsonl"] < min(hashes["phase-one.jsonl"], hashes["phase-two.jsonl"])
    ns = f"{args.catalog}.{args.schema}"
    workspace = Workspace(args.cli, args.profile)
    accepted = workspace.sql(f"SELECT sequence_no,power_w,energy_wh_total FROM {ns}.silver_telemetry ORDER BY sequence_no")
    assert [int(row["sequence_no"]) for row in accepted] == [0, 1, 2]
    assert [Decimal(row["power_w"]) for row in accepted] == [60, 60, 60]
    assert [Decimal(row["energy_wh_total"]) for row in accepted] == [0, 5, 10]
    quarantined = workspace.sql(f"SELECT reason,get_json_object(raw_json,'$.power_w') power_w,get_json_object(raw_json,'$.event_time') event_time FROM {ns}.quarantine ORDER BY reason,power_w")
    assert len(quarantined) == 4
    existing = [row for row in quarantined if row["reason"] == "conflicting_existing_identity"]
    assert sorted(Decimal(row["power_w"]) for row in existing) == [999, 1200]
    assert sum(row["reason"] == "conflicting_device_boot_sequence" for row in quarantined) == 1
    assert sum(row["reason"] == "invalid_protocol_event" and row["event_time"] == "badZ" for row in quarantined) == 1
    replay = compare(after, json.loads(args.replay.read_text(encoding="utf-8"))) if args.replay else None
    if replay:
        assert replay["unchanged"]
    report = {"passed": True, "accepted_events": len(accepted), "quarantined_physical_rows": len(quarantined),
              "covered_energy_before_wh": "0", "covered_energy_after_wh": "10", "unallocated_after_wh": "0",
              "later_conflict_has_earlier_source_hash": True, "accepted_original_payload_unchanged": True,
              "malformed_timestamp_quarantined": True, "replay": replay, "fixture_sha256": hashes,
              "scope": "Two-phase synthetic cloud acceptance, including recursive landing directories"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
