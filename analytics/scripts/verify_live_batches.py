"""Verify immutable exporter manifests, ingest a snapshot, then replay it."""
import argparse
import hashlib
import json
from pathlib import Path

from appliance_analytics.cli import export
from appliance_analytics.ingest import connect, ingest, utc

p=argparse.ArgumentParser()
p.add_argument("--batches",type=Path,default=Path(__file__).resolve().parents[2]/"data"/"batches")
p.add_argument("--db",type=Path,default=Path(__file__).resolve().parents[1]/"data"/"live.duckdb")
p.add_argument("--output",type=Path,default=Path(__file__).resolve().parents[1]/"artifacts"/"live-ingestion-evidence.json")
args=p.parse_args()
paths=sorted(args.batches.glob("*/events.jsonl"))
assert paths,"No completed exporter batches found"
rows=0
ids=set()
for path in paths:
    manifest=json.loads((path.parent/"manifest.json").read_text(encoding="utf-8"))
    content=path.read_bytes()
    events=[json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip()]
    assert hashlib.sha256(content).hexdigest()==manifest["sha256"],f"Batch hash mismatch: {path.parent.name}"
    assert path.parent.name==manifest["sha256"],"Batch directory identity mismatch"
    assert len(events)==manifest["row_count"],"Batch row count mismatch"
    assert hashlib.sha256("\n".join(event["event_id"] for event in events).encode()).hexdigest()==manifest["event_ids_sha256"],"Event-ID manifest mismatch"
    times=[utc(event["event_time"]) for event in events]
    assert min(times)==utc(manifest["event_time_min"]) and max(times)==utc(manifest["event_time_max"]),"Manifest time bounds mismatch"
    rows+=len(events)
    ids.update(event["event_id"] for event in events)
con=connect(args.db)
try:
    first=ingest(con,paths,max_gap_seconds=120)
    def snapshot():
        result=con.execute("SELECT count(*),min(event_time),max(event_time) FROM silver_telemetry").fetchone()
        totals=con.execute("SELECT source_kind,sum(energy_wh),sum(unallocated_energy_wh) FROM gold_device_daily GROUP BY source_kind ORDER BY source_kind").fetchall()
        return {"accepted_events":result[0],"event_time_min":result[1],"event_time_max":result[2],"energy_by_source_kind":totals}
    before=snapshot()
    replay=ingest(con,paths,max_gap_seconds=120)
    after=snapshot()
    assert before==after,"Replay changed identities, time bounds or energy"
    quality=con.execute("SELECT * FROM gold_quality").df().to_dict(orient="records")[0]
    exported=export(con,args.output.parent/"live-powerbi")
finally:
    con.close()
report={"scope":"actual local MQTT-to-Kafka exporter batches; device measurements remain simulated",
        "manifest_verified_batches":len(paths),"physical_rows":rows,"distinct_export_event_ids":len(ids),
        "first_ingest":first,"replay_ingest":replay,"before":before,"after":after,
        "replay_unchanged":before==after,"quality":quality,"exported_tables":exported["tables"]}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
print(json.dumps(report,indent=2,default=str))
