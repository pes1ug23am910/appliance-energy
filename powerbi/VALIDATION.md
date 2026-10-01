# Power BI validation

Recorded on 1 October 2026 with synthetic telemetry labelled `simulated`.

| Check | Result | Evidence boundary |
|---|---|---|
| CSV and Databricks project generation | Two tables, three pages, four measures | The same report structure uses different source expressions |
| Public PBIR schemas | 15 files against nine schemas passed for each variant | JSON structure only |
| Microsoft Tabular deserialization | Both models parsed at compatibility 1567 | Does not refresh data |
| Source-builder regression tests | 12 passed | Covers connector selection, cohort filtering, credential rejection, required columns and escaping |
| CSV Desktop refresh and visuals | All three pages populated | Operator performed refresh; supplied screenshots show overview, quality and forecast rows |
| Read-only query of running Desktop model | Both partitions Ready; exact source comparison passed at absolute tolerance 1e-7 | Actual DAX execution, without modifying the model |
| Databricks Desktop refresh | Operator confirmed success and expected values; populated overview screenshot supplied | User-attested; the report was closed before independent inspection of its loaded source expression |
| Hosted Power BI service | Not tested | No publication, gateway or scheduled-refresh claim |

The independently queried CSV model contained 142 daily rows and 14 forecast rows for two devices. DAX returned **221.27767265635993 kWh** and **0.9859154929577465 mean coverage**. The report displays 221.278 kWh and 98.6%. The one-day forecast interval is distinguished from provisional longer horizons. Device-level interval bounds are not aggregated into a purported fleet interval.

The screenshots retained a pending-query-changes banner. Saving after Apply changes is a separate user action; observed populated visuals and the Ready model partitions establish the refreshed snapshot, not the absence of pending edits.

The sanitized numeric record is [desktop-csv-validation.json](evidence/desktop-csv-validation.json). To repeat the read-only comparison while the report is open, obtain its local Analysis Services port from the active `AnalysisServicesWorkspaces` directory and run:

```powershell
powershell -File scripts/verify_powerbi_refresh.ps1 -Port <local-port> -Data analytics/artifacts/powerbi
```

This helper reads an existing model; it does not click Refresh, sign in, publish, or alter queries. The Databricks report uses the native AWS connector with browser OAuth; no workspace credentials are embedded in the report. CLI authentication is separate from Power BI authentication.
