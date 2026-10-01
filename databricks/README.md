# Databricks adapter

This is executable deployment source, **not an executed cloud deployment**. The local software edition runs without a Databricks account. Account permissions, Free Edition quotas, bundle compatibility and Unity Catalog lineage must be verified in the target workspace.

The three sequential serverless notebook tasks ingest immutable JSONL files into bronze Delta, validate/deduplicate into silver and quarantine, rebuild hourly/daily gold with explicit gap semantics, and evaluate two forecasts with MLflow. No persistent broker, paid endpoint or automatic schedule is created. `max_concurrent_runs: 1` avoids concurrent writers.

Prerequisites: a Unity Catalog catalog you can use, permission to create the schema/tables, an existing UC volume landing directory, Databricks CLI authentication, and a notebook environment with NumPy/pandas/MLflow. Choose the current account's environment; local pinned versions are in `../analytics/pyproject.toml`. Files must be normalized protocol v1 JSONL and each batch at most 16 MiB. Upload only public/synthetic data to Free Edition.

```powershell
cd databricks
databricks bundle validate --var "catalog=workspace,schema=appliance_energy,landing_path=/Volumes/workspace/appliance_energy/landing,max_gap_seconds=120"
databricks bundle deploy --var "catalog=workspace,schema=appliance_energy,landing_path=/Volumes/workspace/appliance_energy/landing,max_gap_seconds=120"
databricks bundle run appliance_lakehouse --var "catalog=workspace,schema=appliance_energy,landing_path=/Volumes/workspace/appliance_energy/landing,max_gap_seconds=120"
```

Use `max_gap_seconds=600` for the deterministic five-minute fixture. Paths and account names above are examples; no credentials belong in files. Provision the volume separately after access/cost review. A Free Edition workspace is not proof of an Azure deployment.

Run `sql/verify.sql` after selecting the catalog/schema, then rerun the same input and compare energy and identity counts. Inject a changed event ID payload, a duplicate, and an out-of-order missing sequence; inspect quarantine and repaired gold. Compare the exported daily results with the local package on the same fixture. The adapters preserve accepted first evidence; for conflicting records first encountered together, local input order and Databricks source-hash order can choose different initial winners. Conflicting data should be reviewed, never silently treated as trusted measurements.

Inspect supported column lineage in Catalog Explorer. Native SQL gold transformations permit lineage capture; the pandas forecasting boundary records table/version provenance in MLflow instead of claiming automatic model column lineage. The forecast stage skips cohorts without 56 consecutive days at >=80% coverage. `forecast_daily` publishes the seasonal-naive reference, while `candidate_forecast_daily` separately labels the calibration-selected research output as unpromoted. Both holdout evaluations stay in MLflow; neither establishes measured-device validation. Multi-day intervals are marked provisional; the measured holdout evaluates one-day forecasts.

The cloud proof is complete only after actual job success, replay comparison, quality cases, MLflow artifacts, warehouse/Power BI connection and selected column lineage are observed. Save sanitized evidence then stop compute. This source has only local syntax checks until that proof occurs.

References: [serverless bundle examples](https://docs.databricks.com/aws/en/dev-tools/bundles/examples), [job parameters](https://docs.databricks.com/aws/en/dev-tools/bundles/job-parameters), [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations), [Unity Catalog lineage](https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-lineage).
