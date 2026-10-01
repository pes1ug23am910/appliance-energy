"""Run the complete offline analytics demonstration, recording actual evidence."""
from pathlib import Path
import json
import time

from appliance_analytics.assistant import evaluate
from appliance_analytics.cli import export
from appliance_analytics.data import fixture
from appliance_analytics.ingest import connect, ingest
from appliance_analytics.models import anomalies, forecast

root = Path(__file__).resolve().parents[1]
data = root / "data"
artifacts = root / "artifacts"
data.mkdir(exist_ok=True)
artifacts.mkdir(exist_ok=True)
started = time.perf_counter()
fixture_report = fixture(data / "reference.jsonl")
con = connect(data / "reference.duckdb")
try:
    ingestion = ingest(con, [data / "reference.jsonl"], max_gap_seconds=600)
    before = con.execute("SELECT sum(energy_wh) FROM gold_device_daily").fetchone()[0]
    replay = ingest(con, [data / "reference.jsonl"], max_gap_seconds=600)
    after = con.execute("SELECT sum(energy_wh) FROM gold_device_daily").fetchone()[0]
    assert before == after, "replay changed energy"
    forecasts = forecast(con, artifacts / "forecast")
    anomaly_report = anomalies(con)
    evaluation = evaluate(con, root / "evals" / "sql_cases.json")
    assert evaluation["failed"] == 0, "assistant evaluation failed"
    exported = export(con, artifacts / "powerbi")
finally:
    con.close()
summary = {"fixture": fixture_report, "ingestion": ingestion, "replay": replay,
           "replay_energy_unchanged": before == after, "energy_wh": before,
           "forecast_series": forecasts["series_evaluated"], "forecast_rows": forecasts["forecast_rows"],
           "forecast_metrics": [{"device_id": r["device_id"], "model": r["model"], **r["metrics"]} for r in forecasts["reports"]],
           "anomalies": anomaly_report, "assistant_evaluation": evaluation,
           "csv_tables": exported["tables"], "elapsed_seconds": time.perf_counter()-started,
           "scope": "deterministic software fixture; no hardware, cloud or real-world predictive claim"}
(artifacts / "demo-evidence.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
print(json.dumps(summary, indent=2, default=str))
