# Power BI energy report

The report builder creates an editable Power BI project with energy overview, coverage investigation and forecast pages. It imports gold CSV snapshots and exposes energy in kWh while retaining unallocated intervals and source labels. Report JSON follows Microsoft's public PBIR schemas; the semantic model uses ordinary Tabular metadata and Power Query CSV imports.

After running the analytics fixture, forecast and export commands, run:

```powershell
uv run --project analytics python scripts/build_powerbi.py --data analytics/artifacts/powerbi --output artifacts/powerbi
uv run --project analytics --with jsonschema==4.25.1 python scripts/validate_powerbi.py artifacts/powerbi
```

Open `artifacts/powerbi/Energy.pbip` in Power BI Desktop and Refresh. DataFolder points to this checkout's export directory. Rebuild after moving the checkout, or update that parameter. SourceKind defaults to `simulated` and filters both tables before aggregation. Choose another cohort with `--source-kind measured|estimated|public_dataset` or edit the Power Query parameter. Exported CSVs and native cache files remain local artifacts.

The source generator is portable. A native Databricks SQL connector variant is available below; local CSV refresh does not establish cloud connector execution. Hosted sharing has separate licensing requirements. The forecast page retains individual device rows rather than silently summing marginal uncertainty intervals.

On 1 October 2026, all 15 schema-bearing project files passed Microsoft's nine referenced schemas. Power BI Desktop refreshed the CSV model and rendered all three pages. A separate read-only DAX query verified 142 daily rows, 14 forecast rows, two devices, 221.27767265636 kWh and mean coverage 0.98591549296 against the source exports. Both model partitions were Ready. See the [validation record](VALIDATION.md) for the distinction between this independently queried local model and the user-confirmed cloud refresh.

References: [PBIP projects](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview), [PBIR files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report), [semantic model files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset).

## Native Databricks source

The same report can import the governed `gold_device_daily` and `forecast_daily` Delta tables. Copy `powerbi/databricks.example.json` to an ignored local path, set the SQL warehouse hostname and HTTP path, and select the actual catalog/schema. `cloud=aws` uses `DatabricksMultiCloud.Catalogs`; `cloud=azure` uses `Databricks.Catalogs`. Both select the ADBC connector implementation 2.0 and retain the source-cohort filter in each table.

```powershell
uv run --project analytics python scripts/build_powerbi.py --data analytics/artifacts/powerbi --databricks-config artifacts/databricks-powerbi-connection.json --output artifacts/powerbi-databricks
uv run --project analytics --with jsonschema==4.25.1 python scripts/validate_powerbi.py artifacts/powerbi-databricks
powershell -File scripts/validate_powerbi_model.ps1 -Project artifacts/powerbi-databricks
```

`--data` supplies column metadata from the matching gold CSV exports; it is not the data source for the Databricks variant. Verify that the cloud tables expose the same columns before refreshing. Connection JSON deliberately rejects additional keys, including tokens/passwords. Sign in through Power BI's native data-source credential prompt; credentials are never embedded in the project. A CLI OAuth login is not a Power BI login.

On 1 October 2026, both report variants passed all 15 schema-bearing files against nine public schemas, and Microsoft's installed Tabular library deserialized both models (two tables, four measures each). Twelve source-builder tests covered connector choice, cohort filtering, credential rejection and equivalent report schemas. Schema/parser checks alone do not establish execution. The operator separately confirmed that this Databricks variant refreshed successfully in Desktop with 221.278 kWh and 14 forecast rows; that cloud refresh is user-attested. Hosted service publication and scheduled refresh have not been tested.

Connector reference: [Databricks Power Query connector](https://learn.microsoft.com/en-us/power-query/connectors/databricks).
