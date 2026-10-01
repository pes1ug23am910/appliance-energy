"""Export bounded cloud reporting tables without copying workspace metadata."""
import argparse
import csv
import json
from pathlib import Path
import re

from verify_cloud import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="databricks")
    parser.add_argument("--profile", default="appliance-energy")
    parser.add_argument("--warehouse-id")
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="appliance_energy")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in (args.catalog, args.schema)):
        raise ValueError("Invalid SQL identifier")
    workspace = Workspace(args.cli, args.profile, args.warehouse_id)
    args.output.mkdir(parents=True, exist_ok=True)
    exported = {}
    for table, order in (("gold_device_daily", "device_id,source_kind,day"),
                         ("forecast_daily", "device_id,source_kind,target_date"),
                         ("anomaly_daily", "device_id,source_kind,day"),
                         ("gold_quality", "bronze_rows")):
        rows = workspace.sql(f"SELECT * FROM {args.catalog}.{args.schema}.{table} ORDER BY {order}")
        if not rows:
            raise RuntimeError(f"Refusing an empty reporting export: {table}")
        with (args.output / f"{table}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        exported[table] = len(rows)
    (args.output / "cloud-export.json").write_text(json.dumps({"rows": exported,
        "scope": "Databricks SQL query result; synthetic input; native Power BI refresh not verified"}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(exported, indent=2))


if __name__ == "__main__":
    main()
