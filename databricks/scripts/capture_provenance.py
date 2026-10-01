"""Save actual UC column lineage and MLflow metrics without account metadata."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from verify_cloud import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="databricks")
    parser.add_argument("--profile", default="appliance-energy")
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="appliance_energy")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item) for item in (args.catalog, args.schema)):
        raise ValueError("Invalid SQL identifier")
    workspace = Workspace(args.cli, args.profile)
    ns = f"{args.catalog}.{args.schema}"
    lineage = []
    for table, column in (("gold_device_daily", "energy_wh"), ("gold_device_hourly", "energy_wh"),
                          ("telemetry_intervals", "delta_wh"), ("silver_telemetry", "energy_wh_total")):
        result = workspace.api("get", "/api/2.0/lineage-tracking/column-lineage",
                               {"table_name": f"{ns}.{table}", "column_name": column})
        lineage.append({"target_table": table, "target_column": column,
                        "upstream": [{"table": col.get("table_name"), "column": col.get("name")}
                                     for col in result.get("upstream_cols", [])]})
    # The user name is used only to locate the personal experiment and is never saved.
    user = workspace.sql("SELECT current_user() user")[0]["user"]
    suffix = "" if args.schema == "appliance_energy" else f"-{args.schema}"
    experiment = workspace.api("get", "/api/2.0/mlflow/experiments/get-by-name",
                               {"experiment_name": f"/Users/{user}/appliance-energy-forecast{suffix}"})
    runs = workspace.api("post", "/api/2.0/mlflow/runs/search", {
        "experiment_ids": [experiment["experiment"]["experiment_id"]],
        "filter": "attributes.status = 'FINISHED'", "order_by": ["attributes.start_time DESC"], "max_results": 100,
    }).get("runs", [])
    seen, records = set(), []
    for run in runs:
        allowed_parameters = {"device_id", "source_kind", "model", "method", "threshold", "label_scope",
                              "holdout_days", "calibration_days", "interval_nominal"}
        params = {entry["key"]: entry["value"] for entry in run.get("data", {}).get("params", [])
                  if entry["key"] in allowed_parameters}
        identity = (params.get("device_id"), params.get("source_kind"), params.get("model"), params.get("method"))
        if identity in seen:
            continue
        seen.add(identity)
        artifact_response = workspace.api("get", "/api/2.0/mlflow/artifacts/list", {"run_id": run["info"]["run_id"]})
        records.append({"parameters": params,
                        "metrics": {entry["key"]: entry["value"] for entry in run.get("data", {}).get("metrics", [])},
                        "status": run["info"]["status"],
                        "artifacts": [{"path": entry["path"], "bytes": entry.get("file_size")}
                                      for entry in artifact_response.get("files", [])
                                      if entry["path"] in {"evaluation.json", "data-provenance.json"}]})
    result = {"captured_at": datetime.now(timezone.utc).isoformat(), "column_lineage": lineage,
              "mlflow_runs": records, "limits": ["Selected captured column edges, not universal lineage coverage",
              "Forecast pandas boundary uses explicit table/version artifact provenance",
              "Synthetic data does not validate measured-appliance predictions"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"lineage_targets": len(lineage), "mlflow_run_groups": len(records),
                      "upstream_edges": sum(len(row["upstream"]) for row in lineage)}, indent=2))


if __name__ == "__main__":
    main()
