# Software edition verification

Executed locally on 1 October 2026. Test counts describe the checked-in implementation at this delivery; they are not coverage percentages or guarantees.

| Area | Executed evidence | Limit |
|---|---|---|
| Java backend | 16 passing tests: 2 unit and 14 PostgreSQL integrations | Disposable database; broker transports tested separately |
| HTTP and TLS MQTT | Seven real transport smoke checks passed | Simulated device; no physical actuation |
| Flutter | 14 tests, clean analyzer, release web build | Native app packaging not exercised |
| Browser recovery | Offline save, full reload, same UUID restored, reconnect, device confirmation; zero page errors | One Chrome browser and local profile |
| Simulator/exporter | Six tests plus 1,000-device local burst | Short shared-host run, not a sustained capacity result |
| Analytics | 45 tests; 40,322 synthetic events and exact energy replay | Synthetic demand/fault labels |
| Live data path | 91 verified MQTT-to-Kafka batches, 1,619 unique events; replay preserved 1.68874305 Wh | Snapshot before later fleet tests; all device readings simulated |
| Forecast | Temporal calibration/holdout and local MLflow artifacts | Seasonal baseline beats challenger; longer horizons provisional |
| Query model | Two real local models evaluated on the same 18 cases; saved SQL replay after guard fixes preserved outcomes | Small fixed suite, not general accuracy |
| Power BI | 15 files validated against public schemas; native Tabular library parsed two tables/four measures | Native visual rendering and CSV refresh unverified |
| Browser energy report | Four input/embedding tests and browser cohort, units and interval checks | Static exported snapshot, not a streaming dashboard |
| Local provisioning | Five bootstrap tests on Linux; four pass plus one POSIX skip on Windows | Local CA and development credentials |
| ESP32 | Ordinary and signed ESP-IDF builds; four host signature checks | No board, electrical, flash power-cut or OTA runtime validation |
| Infrastructure | Bicep compiled; four Kubernetes documents parsed | No Azure/Kubernetes deployment or admission test |

Detailed records: [mobile](../mobile/VALIDATION.md), [analytics](../analytics/VALIDATION.md), [firmware](../firmware/VALIDATION.md), [infrastructure](../infra/VALIDATION.md), [performance](PERFORMANCE.md).

The query evaluation distinguishes answer correctness from blocking unsafe requests. Qwen2.5 Coder 1.5B: 3/12 answerable cases correct, five executed wrong answers, ten guard rejections in all 18 cases, zero model abstentions. Qwen3.5 9B: 11/12 answerable correct, one executed unit error, six model abstentions, zero guard rejections. Both prevented execution in all six unsupported/hostile cases. The deterministic six-intent path passed 17/17 checks and does not claim free-form model generalization.

No physical appliance, Databricks workspace, Unity Catalog lineage inspection, hosted Power BI refresh, Azure service or Kubernetes cluster was tested. BLE provisioning, native mobile packages, hardware telemetry spool durability and production tenant authorization are not implemented by the local demo. These are explicit boundaries, not implied features.

Generated raw telemetry, model weights, local certificates, credentials, databases and build artifacts remain outside the repository. The source includes reproducible commands, original screenshots and compact verification evidence. The six-slide deck is a self-contained HTML presentation.
