# Power BI energy report

The report builder creates an editable Power BI project with energy overview, coverage investigation and forecast pages. It imports gold CSV snapshots and exposes energy in kWh while retaining unallocated intervals and source labels. Report JSON follows Microsoft's public PBIR schemas; the semantic model uses ordinary Tabular metadata and Power Query CSV imports.

After running the analytics fixture, forecast and export commands, run:

```powershell
uv run --project analytics python scripts/build_powerbi.py --data analytics/artifacts/powerbi --output artifacts/powerbi
uv run --project analytics --with jsonschema==4.25.1 python scripts/validate_powerbi.py artifacts/powerbi
```

Open `artifacts/powerbi/Energy.pbip` in Power BI Desktop and Refresh. DataFolder points to this checkout's export directory. Rebuild after moving the checkout, or update that parameter. SourceKind defaults to `simulated` and filters both tables before aggregation. Choose another cohort with `--source-kind measured|estimated|public_dataset` or edit the Power Query parameter. Exported CSVs and native cache files remain local artifacts.

The source generator is portable. A Databricks SQL connector is a later account-backed refresh route; a local CSV report does not establish that integration. Hosted sharing has separate licensing requirements. The forecast page retains individual device rows rather than silently summing marginal uncertainty intervals.

On 1 October 2026, all 15 schema-bearing project files passed Microsoft's nine referenced schemas. Power BI Desktop's installed Tabular libraries deserialized two tables and four measures. These checks do not execute M/DAX, refresh CSVs or render visuals. Native opening/refresh remains a manual acceptance check. A standalone browser energy dashboard supplies a separately rendered local demonstration.

References: [PBIP projects](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview), [PBIR files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report), [semantic model files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset).
