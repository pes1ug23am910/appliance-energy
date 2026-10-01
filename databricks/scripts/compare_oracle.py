"""Compare every exported cloud daily cell with an independent local DuckDB run.

Run this with the analytics environment, which supplies DuckDB. The local database
is opened read-only; no pipeline or forecasting work is silently rerun.
"""
import argparse
import csv
from decimal import Decimal
import json
from pathlib import Path

import duckdb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-db", type=Path, required=True)
    parser.add_argument("--cloud-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.cloud_csv.open(encoding="utf-8", newline="") as stream:
        cloud = list(csv.DictReader(stream))
    connection = duckdb.connect(str(args.local_db), read_only=True)
    try:
        cursor = connection.execute("SELECT * FROM gold_device_daily ORDER BY device_id,source_kind,day")
        columns = [item[0] for item in cursor.description]
        local = [dict(zip(columns, values)) for values in cursor.fetchall()]
    finally:
        connection.close()
    key = lambda row: (str(row["device_id"]), str(row["source_kind"]), str(row["day"]))
    left, right = {key(row): row for row in local}, {key(row): row for row in cloud}
    if len(left) != len(local) or len(right) != len(cloud) or left.keys() != right.keys():
        raise AssertionError("Duplicate or mismatched device/source/day identities")
    errors = []
    for identity, expected in left.items():
        actual = right[identity]
        if set(expected) != set(actual):
            raise AssertionError("Local and cloud reporting schemas differ")
        for column in columns:
            x, y = expected[column], actual[column]
            if x is None:
                equal = y in (None, "")
            elif isinstance(x, bool):
                equal = y.lower() == str(x).lower()
            elif isinstance(x, (int, float, Decimal)):
                equal = abs(Decimal(str(x)) - Decimal(y)) <= Decimal("0.0000001")
            else:
                equal = str(x) == y
            if not equal:
                errors.append({"identity": identity, "column": column, "local": str(x), "cloud": y})
    report = {"source": "Existing independently computed DuckDB database opened read-only",
              "cloud_source": "Actual Databricks SQL export after successful serverless job",
              "rows_compared": len(left), "columns_compared": len(columns), "numeric_absolute_tolerance": "0.0000001",
              "local_energy_wh": str(sum(row["energy_wh"] for row in local)),
              "cloud_energy_wh": str(sum(Decimal(row["energy_wh"]) for row in cloud)),
              "mismatches": errors, "passed": not errors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
