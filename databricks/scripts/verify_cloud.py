"""Capture small, account-redacted verification snapshots using an authenticated CLI.

Authentication stays in the Databricks CLI profile. This helper never prints tokens,
workspace identifiers, experiment owners or raw input rows.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time


class Workspace:
    def __init__(self, cli: str, profile: str, warehouse: str | None = None):
        self.cli, self.profile, self.warehouse = cli, profile, warehouse

    def command(self, *args: str):
        result = subprocess.run([self.cli, *args, "--profile", self.profile, "--output", "json"],
                                text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Databricks command failed ({args[0]} {args[1]}). Inspect the CLI privately.")
        return json.loads(result.stdout or "{}")

    def api(self, method: str, path: str, body: dict | None = None):
        if body is None:
            return self.command("api", method, path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as request:
            json.dump(body, request)
            request_path = Path(request.name)
        try:
            return self.command("api", method, path, "--json", f"@{request_path}")
        finally:
            request_path.unlink(missing_ok=True)

    def sql(self, statement: str):
        if self.warehouse is None:
            warehouses = self.command("warehouses", "list")
            available = [item for item in warehouses if item.get("enable_serverless_compute")]
            if len(available) != 1:
                raise RuntimeError("Specify --warehouse-id when the workspace has other than one serverless warehouse")
            self.warehouse = available[0]["id"]
        response = self.api("post", "/api/2.0/sql/statements", {
            "warehouse_id": self.warehouse, "statement": statement,
            "wait_timeout": "0s", "on_wait_timeout": "CONTINUE", "row_limit": 1000,
        })
        deadline = time.monotonic() + 600
        while response["status"]["state"] in {"PENDING", "RUNNING"}:
            if time.monotonic() > deadline:
                self.api("post", f"/api/2.0/sql/statements/{response['statement_id']}/cancel", {})
                raise TimeoutError("SQL verification exceeded ten minutes and was cancelled")
            time.sleep(3)
            response = self.api("get", f"/api/2.0/sql/statements/{response['statement_id']}")
        if response["status"]["state"] != "SUCCEEDED":
            code = response["status"].get("error", {}).get("error_code", "UNKNOWN")
            raise RuntimeError(f"SQL verification failed: {code}")
        manifest = response["manifest"]
        if manifest.get("truncated") or manifest.get("total_chunk_count", 1) > 1:
            raise RuntimeError("Verification query exceeded its bounded result limit")
        names = [column["name"] for column in manifest["schema"]["columns"]]
        return [dict(zip(names, row)) for row in response.get("result", {}).get("data_array", [])]


def snapshot(workspace: Workspace, catalog: str, schema: str):
    for value in (catalog, schema):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Invalid catalog/schema identifier")
    ns = f"{catalog}.{schema}"
    queries = {
        "quality": f"SELECT * FROM {ns}.gold_quality",
        "identity": f"SELECT count(*) accepted_events,count(DISTINCT event_id) distinct_events,count(DISTINCT struct(device_id,boot_id,sequence_no)) distinct_slots FROM {ns}.silver_telemetry",
        "energy": f"SELECT source_kind,count(*) daily_rows,sum(energy_wh) energy_wh,sum(unallocated_energy_wh) unallocated_energy_wh,sum(coverage_seconds) coverage_seconds,sum(reading_count) reading_count FROM {ns}.gold_device_daily GROUP BY source_kind ORDER BY source_kind",
        "invariants": f"SELECT count(*) invalid_rows FROM {ns}.gold_device_daily WHERE energy_wh<0 OR coverage_ratio<0 OR coverage_ratio>1",
        "quarantine": f"SELECT reason,count(*) rows FROM {ns}.quarantine GROUP BY reason ORDER BY reason",
        "forecast": f"SELECT model,count(*) rows,min(prediction_wh) minimum_wh,max(horizon_days) maximum_horizon FROM {ns}.forecast_daily GROUP BY model ORDER BY model",
        "candidate": f"SELECT model,release_status,count(*) rows FROM {ns}.candidate_forecast_daily GROUP BY model,release_status ORDER BY model",
        "anomaly": f"SELECT source_kind,count(*) rows,sum(CASE WHEN is_alert THEN 1 ELSE 0 END) alerts FROM {ns}.anomaly_daily GROUP BY source_kind ORDER BY source_kind",
        "columns": f"SELECT table_name,column_name,data_type FROM {catalog}.information_schema.columns WHERE table_schema='{schema}' ORDER BY table_name,ordinal_position",
    }
    return {"captured_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Databricks Free Edition, synthetic fixture; account identifiers omitted",
            **{name: workspace.sql(sql) for name, sql in queries.items()}}


def compare(before: dict, after: dict):
    fields = ["quality", "identity", "energy", "invariants", "quarantine", "forecast", "candidate", "anomaly", "columns"]
    changed = [field for field in fields if before.get(field) != after.get(field)]
    return {"compared_fields": fields, "unchanged": not changed, "changed_fields": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="databricks")
    parser.add_argument("--profile", default="appliance-energy")
    parser.add_argument("--warehouse-id")
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="appliance_energy")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path, help="Earlier snapshot for replay comparison")
    args = parser.parse_args()
    result = snapshot(Workspace(args.cli, args.profile, args.warehouse_id), args.catalog, args.schema)
    if args.compare:
        result["replay"] = compare(json.loads(args.compare.read_text(encoding="utf-8")), result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot_written": True, "identity": result["identity"], "energy": result["energy"],
                      "replay": result.get("replay")}, indent=2))
    if result.get("replay", {}).get("unchanged") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
