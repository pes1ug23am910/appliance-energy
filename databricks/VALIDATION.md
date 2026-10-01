# Databricks Free Edition verification

Date: 1 October 2026. These are actual account executions using synthetic data, not local Spark emulation. OAuth credentials, workspace/warehouse identifiers, user names and private run links are excluded from the checked-in evidence.

## Reference lakehouse

The deployed bundle ran its ingest, model and forecast tasks successfully, then completed an unchanged-input replay. It used Standard serverless environment version 5, one concurrent run, no recurring trigger and a ten-minute auto-stop SQL warehouse. The initial job took 548.833 seconds and replay 476.224 seconds, including platform startup; these are observation records, not performance guarantees. The accepted-identity correction also passed a full reference run. After the final quarantine-key correction, the model and forecast tasks passed against the same unchanged reference bronze table; that targeted run deliberately skipped ingestion. The [run summary](evidence/run-summary.json) distinguishes complete and partial runs and records final notebook hashes.

| Check | Observed result |
| --- | --- |
| Immutable input | One normalized synthetic JSONL file, 16,005,608 bytes |
| Bronze and silver | 40,322 bronze rows and accepted events; 40,322 distinct event IDs and device/boot/sequence identities |
| Daily gold | 142 rows across two simulated devices, including partial endpoint days |
| Covered energy | 221,277.67265636 Wh |
| Unallocated energy / quarantine | Zero / zero for the reference fixture |
| Replay | All nine snapshot sections unchanged: quality, identities, energy, invariants, quarantine, baseline forecast, candidate forecast, anomalies and schemas |
| Independent local comparison | All 142 daily rows and 14 columns matched the existing read-only DuckDB oracle; numeric tolerance 0.0000001 and exact aggregate energy equality |
| Reporting export | Actual SQL exports: 142 daily rows, 14 baseline forecast rows, 98 anomaly rows and one quality row |

All created pipeline tables use managed Delta storage. The reference gap policy is 600 seconds for five-minute samples. SQL validation found no duplicate identities and no negative energy or out-of-range coverage ratios. The result remains synthetic-device evidence.

## Forecast and lineage evidence

The managed MLflow experiment returned five finished run groups: four forecast evaluations and one labelled anomaly evaluation. Each forecast evaluation contains `evaluation.json` and `data-provenance.json`. Seasonal-naive holdout MAE was 148.2581 Wh and 167.4581 Wh for the two fixture devices; ridge-calendar MAE was worse at 390.3718 Wh and 444.3043 Wh. The published 14-row table retains the seasonal-naive baseline, and the research candidate remains separately labelled as unpromoted. Ninety-percent intervals are a nominal target; days two through seven remain provisional.

Anomaly evaluation recorded six true positives, two false positives and zero false negatives: precision 0.75 and recall 1.0 on 98 explicitly labelled simulated days. These are injected-scenario results, not measured fault-detection accuracy.

The Unity Catalog column-lineage API returned 12 upstream edges across four requested targets, including this energy path:

```text
bronze_events.raw_json
  -> silver_telemetry.energy_wh_total
  -> telemetry_intervals.delta_wh
  -> gold_device_hourly.energy_wh
  -> gold_device_daily.energy_wh
```

The full response also records temporal/grouping inputs to the intermediate expressions. This proves selected captured mappings, not every possible column transformation. Forecasting crosses into pandas; its table/version provenance is explicitly logged in MLflow rather than presented as automatic model column lineage.

## Quality checks

The final isolated quality schema's first successful run accepted two readings separated by one missing sequence. It reported zero covered energy and 10 Wh of unallocated counter energy. This preserves the gap instead of inventing coverage. The second phase was uploaded into a nested landing subdirectory and added the late reading, a delivery duplicate, two changed immutable payloads, a device/boot/sequence collision and a malformed timestamp. One conflicting file was deliberately constructed with a content hash sorting before the original accepted evidence.

The second run accepted exactly three unique identities, repaired the missing interval to 600 covered seconds and 10 Wh, and reduced unallocated energy to zero. Four physical rows were quarantined: the two changed payloads, the colliding slot and the malformed timestamp. All accepted power values remained 60 W; neither the 999 W nor 1,200 W conflicting payload replaced the original. A third unchanged-input run preserved all nine snapshot sections, including the four quarantine records and their original classifications. The [quality assertions](evidence/quality-assertions.json) record the fixture hashes and exact checks. The small quality cohort correctly produced no forecasts.

Runtime preparation corrected unsafe timestamp parsing to `try_to_timestamp`, enabled recursive input directories and explicitly selected serverless environment version 5. Existing silver identities are checked before new batch winners are chosen. Quarantine IDs use the immutable physical source hash and row number, preserving one record even when later state changes the conflict classification. Separate quality schemas use separate MLflow experiments.

## Reproduction and limits

Use the commands in [README.md](README.md). `scripts/verify_cloud.py` saves bounded SQL snapshots and detects replay differences; `scripts/compare_oracle.py` compares every daily reporting cell with the independent local database. `scripts/capture_provenance.py` fetches actual lineage and MLflow data, and `scripts/export_gold.py` produces the reporting CSVs. The checked-in [evidence directory](evidence/) contains sanitized results.

The operator reported a successful refresh of the Databricks Power BI report and supplied a populated overview screenshot. That is operator-attested native refresh evidence; the CLI checks independently establish SQL access and exports, without inspecting the closed cloud report's live partitions. No second-principal least-privilege test, continuous broker-to-cloud ingestion, Azure Databricks deployment or measured hardware validation is implied. Gold tables are replaced separately, so reporting consumers should read after a completed job. No serving endpoint or recurring job was created.

After the final evidence queries, the SQL warehouse was explicitly stopped. Its API response reported `STOPPED` and zero active sessions. The manual job definition, Delta tables, synthetic landing data and managed MLflow artifacts remain available for a later demonstration.
