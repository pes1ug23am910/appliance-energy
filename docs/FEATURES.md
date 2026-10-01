# Capabilities and remaining acceptance

The software/simulator edition is implemented. The rows below separate executed acceptance from work still in progress. Proposed extensions retain **IN PROGRESS** as a tracking status; that label does not mean their implementation or acceptance has finished.

| Capability | Current evidence | Remaining scope: IN PROGRESS |
|---|---|---|
| Reliable device control | Java/PostgreSQL twin, immutable command IDs, revision/expiry checks, transactional outboxes, TLS MQTT reports and real transport checks | Physical low-voltage output and independent actuator feedback |
| Offline operator app | Flutter web recovery plus native Android SQLite test and debug APK | Physical Android acceptance, release signing and other native targets |
| Device firmware | ESP32 C firmware, persisted settings, safe restart rules, bounded immutable telemetry spool and host fault tests | Board power-cut tests, flash behavior, actual Wi-Fi reconnect and measured sensors |
| Signed updates | ESP32 signed build and valid/tampered/wrong-key/unsigned host checks | On-device HTTPS update, failed-boot rollback, interrupted update and key lifecycle |
| Provisioning | ESP32 BLE implementation with required proof of possession compiles | Physical BLE onboarding and ownership reset acceptance |
| Telemetry ingestion | Persistent simulator, MQTT receipts, Kafka outbox and replay-safe batch exports | Hardware spool durability, prolonged outages and continuous cloud landing |
| Lakehouse/orchestration | Local DuckDB oracle and executed Databricks Delta jobs; duplicate, late and conflicting input checks | Scheduled ingestion, broader recovery/failure cases and larger measured cohorts |
| Governance | Selected Unity Catalog column lineage; model table/version provenance logged in MLflow | Second-principal least-privilege tests and broader lineage coverage |
| Reporting | Three-page Power BI Desktop CSV report; independent DAX checks; cloud refresh user-attested | Hosted refresh, sharing and account permission acceptance |
| Forecasting | Seasonal baseline and ridge challenger, temporal evaluation and managed/local MLflow | Prospective measured-device evaluation and multi-day uncertainty calibration |
| Anomaly detection | Precision/recall against labelled synthetic injections | Independent real-fault labels and maintenance usefulness |
| Ask data | Deterministic intents, optional local SQL model, read-only AST policy and wrong-answer evaluation | Broader unit/grain/date/ambiguity evaluation; optional hosted provider route |
| Fleet performance | Recorded 1,000-device burst with exact generated/received counts | Longer controlled soaks, outage recovery and declared resource/latency targets |
| Azure deployment | Actual temporary-VM transport and five-minute 100-device fleet acceptance, exact Kafka/API reconciliation and bounded teardown tooling | Production ingress/identity, managed dependencies, backup/restore and deployment rollback |
| Kubernetes / AKS extension | Private one-replica backend manifests parsed | Admission, startup, dependency mounting, restart/rescheduling, network policy and actual AKS acceptance |
| Data Factory extension | Retained design scope | Implement ingestion/retries and prove idempotent reruns |
| IoT Hub extension | Retained design scope | Implement protocol mapping with one desired-state authority and test actual service behavior |
| FlashKV / Zephyr extension | Retained compatibility experiment; current firmware uses NVS | Implement adapter and independent power-loss tests |
| Neural comparison extension | Retained research question; baseline results available | Bounded experiment with unchanged temporal splits and measured cost |
| Consulting close | Fictional brief, KPIs, recommendation memo, six-slide deck and two demo runbooks | Measured pilot, prospective evaluation and intervention study before estimating benefits |

See [validation](VALIDATION.md) for dated results and [the recommendation](RECOMMENDATION.md) for the business decision. No physical exactly-once guarantee, actual client engagement, field accuracy, production capacity or energy saving follows from the current demonstration.
