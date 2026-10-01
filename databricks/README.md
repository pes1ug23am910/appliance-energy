# Databricks adapter

The three-stage bundle has been executed in **Databricks Free Edition** on synthetic appliance data. Delta tables, managed MLflow runs and selected Unity Catalog column-lineage edges were observed through the workspace APIs. See [VALIDATION.md](VALIDATION.md) for dated results and the remaining native Power BI and access-control boundaries. The local software edition still runs without an account.

The three sequential serverless notebook tasks ingest immutable JSONL files into bronze Delta, validate/deduplicate into silver and quarantine, rebuild hourly/daily gold with explicit gap semantics, and evaluate two forecasts with MLflow. No persistent broker, paid endpoint or automatic schedule is created. `max_concurrent_runs: 1` avoids concurrent writers.

Prerequisites: a Unity Catalog catalog you can use, permission to create the schema/tables, an existing UC volume landing directory and Databricks CLI authentication. The bundle selects the Standard serverless environment version 5, which provides the required scientific and MLflow libraries. Files must be normalized protocol v1 JSONL and each batch at most 16 MiB. Nested exporter batch directories are supported. Upload only public/synthetic data to Free Edition.

Run the following commands from this `databricks` directory. Authenticate with OAuth in your browser; do not paste a token into a notebook or repository:

```powershell
databricks auth login --host https://YOUR-WORKSPACE.cloud.databricks.com --profile appliance-energy
databricks catalogs list --profile appliance-energy
databricks schemas create appliance_energy workspace --profile appliance-energy
databricks volumes create workspace appliance_energy landing MANAGED --profile appliance-energy
databricks fs cp ..\analytics\data\reference.jsonl dbfs:/Volumes/workspace/appliance_energy/landing/reference.jsonl --profile appliance-energy
```

Create the schema and volume only when absent; use an existing authorized catalog if its name differs. The full 70-day fixture is approximately 16 MB and fits the per-file cap. The API upload is a batch transfer; it does not expose the local broker to the internet.

```powershell
databricks bundle validate --profile appliance-energy --var "catalog=workspace,schema=appliance_energy,landing_path=/Volumes/workspace/appliance_energy/landing,max_gap_seconds=600"
databricks bundle deploy --profile appliance-energy --var "catalog=workspace,schema=appliance_energy,landing_path=/Volumes/workspace/appliance_energy/landing,max_gap_seconds=600"
databricks bundle run appliance_lakehouse --profile appliance-energy --var "catalog=workspace,schema=appliance_energy,landing_path=/Volumes/workspace/appliance_energy/landing,max_gap_seconds=600"
```

Use `max_gap_seconds=600` for the deterministic five-minute fixture; use 120 for the live simulator's shorter sampling interval. Paths and account names above are examples; no credentials belong in files. A Free Edition workspace is not proof of an Azure deployment.

Run `sql/verify.sql` after selecting the catalog/schema, then rerun the same input and compare energy and identity counts. Inject a changed event ID payload, a duplicate, and an out-of-order missing sequence; inspect quarantine and repaired gold. Compare the exported daily results with the local package on the same fixture. The adapters preserve accepted first evidence; for conflicting records first encountered together, local input order and Databricks source-hash order can choose different initial winners. Conflicting data should be reviewed, never silently treated as trusted measurements.

Inspect supported column lineage in Catalog Explorer. Native SQL gold transformations permit lineage capture; the pandas forecasting boundary records table/version provenance in MLflow instead of claiming automatic model column lineage. The forecast stage skips cohorts without 56 consecutive days at >=80% coverage. `forecast_daily` publishes the seasonal-naive reference, while `candidate_forecast_daily` separately labels the calibration-selected research output as unpromoted. Both holdout evaluations stay in MLflow; neither establishes measured-device validation. Multi-day intervals are marked provisional; the measured holdout evaluates one-day forecasts.

After a successful run, capture a small account-redacted snapshot, run the same input again and compare:

```powershell
python scripts/verify_cloud.py --output ../artifacts/cloud-before.json
# Rerun the same bundle, then:
python scripts/verify_cloud.py --compare ../artifacts/cloud-before.json --output ../artifacts/cloud-after.json
python scripts/capture_provenance.py --output ../artifacts/cloud-provenance.json
python scripts/export_gold.py --output ../artifacts/cloud-powerbi
uv run --locked --project ../analytics python scripts/compare_oracle.py --local-db ../analytics/data/reference.duckdb --cloud-csv ../artifacts/cloud-powerbi/gold_device_daily.csv --output ../artifacts/cloud-oracle.json
```

The scripts use the authenticated CLI profile, bound query results to 1,000 rows and exclude workspace/owner identifiers from their outputs. Supply `--cli` when the executable is not on PATH. A warehouse is selected automatically only when exactly one serverless warehouse exists; `verify_cloud.py` and `export_gold.py` also accept `--warehouse-id`.

`python scripts/quality_fixture.py --output <local-folder>` creates two tiny input phases and an adversarial `earlier-hash-conflict.jsonl`. Run phase one in a separate schema and landing volume, capture its snapshot, then upload both remaining JSONL files into an `incremental/` subdirectory and rerun with the same quality schema. Use bundle `--params schema=appliance_energy_checks,landing_path=/Volumes/workspace/appliance_energy_checks/landing,max_gap_seconds=600` to override only that run. Capture the second snapshot, rerun unchanged input and capture a third. Then use `python scripts/verify_quality.py --before <first-snapshot> --after <second-snapshot> --replay <third-snapshot> --fixture-folder <local-folder> --output <report>` to assert gap repair, duplicate suppression, conflicting payloads, slot collisions, malformed UTC timestamps and accepted evidence taking precedence over a later file with an earlier hash. Quality schemas receive a separate MLflow experiment so their empty forecast cohorts cannot replace reference evaluation evidence.

The gold tables are replaced individually rather than in one cross-table transaction. Consumers should read after job completion. Account-level least-privilege tests with a second principal remain a separate acceptance step. The dated validation record distinguishes operator-attested native Power BI refresh from independently queried SQL results. Stop the SQL warehouse after verification; no notebook job schedule or serving endpoint is created.

References: [serverless bundle examples](https://docs.databricks.com/aws/en/dev-tools/bundles/examples), [job parameters](https://docs.databricks.com/aws/en/dev-tools/bundles/job-parameters), [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations), [Unity Catalog lineage](https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-lineage).
