# Recommendation to the appliance service manager

**Proceed with a measured pilot, retaining the seasonal baseline and explicit operator confirmation.** This demonstration establishes a reproducible software workflow. It does not establish energy savings, appliance fault prediction or production readiness.

The control demonstration preserved a command's identity across offline storage, a page reload and reconnection. The device then confirmed the same command through TLS MQTT. Operators should distinguish queued, delivered, confirmed and unknown outcomes. A missing acknowledgement requires reconciliation; it is not a reason to send a new toggle command.

For energy investigations, rank devices within the same source cohort and comparable observation coverage. Keep energy across long gaps in the unallocated category. The transport replay snapshot preserved 1,619 unique simulated observations and 1.68874305 Wh across 91 immutable batches. This short live run tests accounting and transport, not seasonal demand.

The longer experiment uses two synthetic 70-day device histories. The calibration-selected ridge model performed worse on untouched holdout data:

| Device | Seasonal-naive MAE, Wh/day | Ridge MAE, Wh/day |
|---|---:|---:|
| fixture-1 | 148.26 | 390.37 |
| fixture-2 | 167.46 | 444.30 |

Keep seasonal-naive as the reference forecast. Preserve the challenger result instead of promoting complexity without evidence. Forecast intervals need prospective coverage checks; longer-horizon ranges remain provisional. The anomaly experiment's precision 0.75 and recall 1.0 apply only to injected, labelled synthetic anomalies. They do not estimate real maintenance performance.

The query model also needs review. In the initial fixed 18-case evaluation, Qwen3.5 9B answered 11/12 business questions correctly and refused all six unsupported/hostile requests; one executed answer used the wrong energy unit. Qwen2.5 Coder 1.5B answered 3/12 correctly, while execution guards blocked the six safety cases. Safety checks and semantic correctness are separate. Keep the six deterministic intents available, show generated SQL, and require review of model answers.

The Databricks run matches all 142 daily rows and 14 columns of the local reference oracle, with exactly 221,277.67265636 Wh preserved on replay. Selected Unity Catalog column-lineage paths and managed MLflow provenance were inspected. The Power BI CSV model independently reproduces these reference totals; its native cloud connector refresh is operator-attested. These checks establish reproducible reporting on simulated observations.

Next, use a low-voltage bench setup and measured sensors. The ESP8266 adapter supports a separate state/telemetry path; retain the ESP32 target for BLE and signed-update rollback acceptance. Test power cuts during state persistence and OTA, verify rollback on the board, and measure prospective forecast coverage. Follow those checks with an intervention study before estimating benefits or replacing the baseline. No physical deployment, measured energy saving or actual client outcome is established.
