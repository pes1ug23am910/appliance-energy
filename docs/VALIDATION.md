# Software and cloud verification

Recorded on 1 October 2026. Counts describe specific runs and datasets; they are not coverage percentages or guarantees.

The [clean-clone workflow](https://github.com/pes1ug23am910/appliance-energy/actions/runs/36901022460) passed all five jobs for source commit `a22d4b95`: backend PostgreSQL tests, Python analytics/simulator/provisioning/reporting tests, Flutter checks, actual HTTP/TLS MQTT integration, and native Android persistence/package checks. Component records distinguish later environment executions and their exact source hashes.

| Area | Executed evidence | Limit |
|---|---|---|
| Java backend | 16 tests: 2 unit and 14 PostgreSQL integrations | Disposable database; broker transports checked separately |
| HTTP and TLS MQTT | Seven actual transport checks | Simulated device; no physical actuation |
| Flutter | 14 tests, clean analyzer, release web build | Single-operator prototype |
| Android | API 35 emulator exercised native SQLite close/reopen, immutable retry, large revisions and origin isolation; ARM64/x86_64 debug APK built in CI and locally | Emulator persistence test does not contact the backend; no physical phone or store release |
| Browser recovery | Offline save, full reload, same UUID restored, reconnect and simulator confirmation; zero page errors | One Chrome browser/profile |
| Simulator/exporter | Persistent events and receipts; 1,000-device local burst | Short shared-host result, not sustained capacity |
| Local analytics | 45 tests; 40,322 synthetic events and exact energy replay | Synthetic demand and fault labels |
| Local live data path | 91 verified MQTT-to-Kafka batches, 1,619 unique events; replay preserved 1.68874305 Wh | Snapshot predates later fleet checks; readings simulated |
| Databricks | Actual serverless ingest/model/forecast jobs, managed Delta tables, reference replay and adversarial late/conflicting-data replay | Manual runs on synthetic data; continuous cloud ingestion unverified |
| Reference comparison | All 142 daily gold rows and 14 columns matched the independent DuckDB oracle; 221,277.67265636 Wh preserved | Two fixture devices, including partial endpoint days |
| Unity Catalog / MLflow | 12 upstream edges across four selected target columns; five finished MLflow run groups; four forecast groups contain evaluation/provenance artifacts | Selected lineage only; pandas model provenance logged separately; no second-principal permission test |
| Forecast/anomaly | Temporal calibration/holdout; seasonal baseline beats ridge; labelled injected-anomaly evaluation | Longer forecast horizons provisional; no field-failure labels |
| Query model | Two local models evaluated on 18 cases; saved SQL replay preserved outcomes after guard fixes | Small fixed suite; safe SQL may still answer incorrectly |
| Power BI | Both generated variants passed schema/Tabular checks; native CSV model DAX independently matched energy, coverage and row counts; user confirmed three-page CSV rendering and cloud connector refresh | Cloud native refresh is user-attested; no hosted Power BI service refresh/sharing |
| Browser energy report | Four input/embedding tests and browser cohort, units and interval checks | Static exported snapshot |
| ESP32 | Ordinary, signed and BLE/signed profiles compiled; nine sanitizer-backed C spool fault suites; four host signature checks per signed profile | No board, electrical, flash power-cut, radio or device OTA execution |
| Azure runtime | Seven transport checks; 100-device five-minute run with 3,000/3,000 receipts, zero dropped/pending; two 3,001-event Kafka exports matched PostgreSQL/API | Temporary single-host VM, simulated devices; not AKS, IoT Hub or a capacity SLA |
| Infrastructure tooling | Archive timestamp/migration regression passed; Bicep compiled and four Kubernetes documents parsed | Kubernetes admission/runtime unverified; teardown and cost evidence are recorded separately |

Detailed records: [mobile](../mobile/VALIDATION.md), [analytics](../analytics/VALIDATION.md), [Databricks](../databricks/VALIDATION.md), [Power BI](../powerbi/VALIDATION.md), [firmware](../firmware/VALIDATION.md), [infrastructure](../infra/VALIDATION.md), and [performance](PERFORMANCE.md).

The native CSV model returned 221.27767265635993 kWh, mean coverage 0.9859154929577465, two devices, 142 energy rows and 14 forecast rows. Both partitions were Ready. The displayed headline KPIs after a cloud-report refresh are operator-attested; the cloud model had closed before independent partition inspection. These evidence levels remain separate.

The query evaluation distinguishes correct answers from blocked requests. Qwen2.5 Coder 1.5B: 3/12 answerable cases correct, five executed wrong answers, ten guard rejections across all 18 cases, zero model abstentions. Qwen3.5 9B: 11/12 answerable correct, one executed unit error, six model abstentions, zero guard rejections. Both prevented execution in all six unsupported/hostile cases. The deterministic six-intent path passed 17/17 checks and does not establish free-form generalization.

No physical appliance, calibrated energy sensor, physical phone, device OTA rollback, production tenant authorization or Kubernetes cluster is established by these results. ESP32 BLE provisioning and receipt-driven NVS telemetry persistence are implemented and compiled; physical acceptance remains open. See the [capability and remaining-scope matrix](FEATURES.md).

Raw telemetry, credentials, certificates, model weights, databases and build outputs remain outside source control. The repository contains reproduction commands, original screenshots and compact sanitized evidence. The six-slide deck remains a self-contained HTML presentation.
