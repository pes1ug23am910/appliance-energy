"""Copy compact, credential-free verification outputs into the documentation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence"


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    for name in ("integration-smoke.json", "mobile-browser-smoke.json"):
        path = ROOT / "artifacts" / name
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            # Browser evidence is summarized explicitly in mobile/VALIDATION.md.
            if name == "integration-smoke.json":
                save(name, value)
    experiments = []
    for name in ("fleet-100-final.json", "fleet-100-tuned.json", "fleet-1000.json"):
        path = ROOT / "artifacts" / name
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        summary = {key: val for key, val in value.items() if key not in ("devices", "initial_device_counters")}
        summary["artifact"] = name
        summary["accepted_delta"] = sum(device["accepted"] - value["initial_device_counters"][key]["accepted"] for key, device in value["devices"].items())
        summary["dropped_delta"] = sum(device["dropped"] - value["initial_device_counters"][key]["dropped"] for key, device in value["devices"].items())
        summary["pending_at_end"] = sum(device["pending"] for device in value["devices"].values())
        experiments.append(summary)
    save("fleet-bursts.json", {"date": "2026-10-01", "shared_host": True, "experiments": experiments})
    path = ROOT / "artifacts/telemetry-query-plan.json"
    if path.exists():
        save("telemetry-query-plan.json", json.loads(path.read_text(encoding="utf-8-sig")))
    path = ROOT / "artifacts/powerbi/schema-validation.json"
    if path.exists():
        save("powerbi-schema-validation.json", json.loads(path.read_text(encoding="utf-8")))
    print("Compact local evidence copied to docs/evidence; credentials and raw telemetry excluded.")


if __name__ == "__main__":
    main()
