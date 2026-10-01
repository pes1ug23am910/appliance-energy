# Appliance Energy

A smart-appliance control system and an energy analytics case study. One telemetry contract connects a Flutter operator console, a Java device-twin service, a durable simulator, MQTT, Kafka, and a lakehouse workflow.

The fictional client asks: **Which devices need investigation, and how much energy should we expect next week?** The answer includes observation coverage and uncertainty. A delivered command is not treated as a confirmed physical outcome.

Two demonstrations share the same system:

1. **Reliable control:** queue an absolute fan setpoint, disconnect, retry the same command, and reconcile the device report without creating another logical command.
2. **Energy decisions:** ingest immutable telemetry batches, replay them without double-counting, inspect coverage, compare forecasts, and query approved gold tables.

This is the software and simulator edition. Real HTTP, TLS MQTT, PostgreSQL, Kafka, SQLite, Flutter web/Android and local analytics execute here. The Databricks Free Edition pipeline also ran against the synthetic reference dataset, with Delta tables, selected Unity Catalog column lineage and managed MLflow evidence. Power BI Desktop reporting has separate native validation. A temporary Azure VM passed transport and five-minute fleet reconciliation checks; its services were removed after verification. ESP32 firmware compiles with persistent telemetry, BLE provisioning and signed updates; physical hardware behavior remains unverified. The [validation record](docs/VALIDATION.md) states the scope of each environment.

## Start locally

Requirements: Docker with Compose, Python 3.12, [uv](https://docs.astral.sh/uv/), and enough disk space for container images. Flutter is needed only for the operator console. Windows was exercised locally; Linux is covered by the verification workflow.

From the repository root:

```sh
uv sync --project simulator --locked --python 3.12
uv run --project simulator python scripts/bootstrap.py --devices 100
docker compose up -d --build --wait
uv run --project simulator python scripts/with_env.py uv run --project simulator python scripts/smoke.py
```

The first build downloads dependencies. If the API is still starting, wait until the backend startup message before running the smoke test. The bootstrap creates a local CA, per-device broker credentials and an operator token in ignored `.runtime/` and `.env` files. It preserves existing credentials on subsequent runs. Do not commit or share these files.

Run devices for one minute, then export the Kafka backlog:

```sh
uv run --project simulator python scripts/with_env.py uv run --project simulator appliance-simulator run --count 10 --interval 2 --duration 60
uv run --project simulator appliance-simulator export --once
```

`--once` drains until the assigned consumer has three empty polls. A continuously publishing fleet can keep it running. Kafka batches are written under `data/batches/` before offsets are committed; stable event IDs make replay safe. The exporter uses a stable consumer group, so a second run normally resumes from committed offsets.

Start the [Flutter console](mobile/README.md), open `http://127.0.0.1:8090`, select backend `http://127.0.0.1:18080`, and enter the operator token from the local `.env`. The token stays in memory. Use the same browser origin after a reload to recover its command queue.

Stop the services with `docker compose down`. Named volumes retain data. Removing volumes is an explicit reset, not part of normal shutdown.

## Run the energy case

```sh
uv sync --project analytics --locked --python 3.12
cd analytics
uv run --locked python scripts/run_demo.py
```

This produces two 70-day synthetic device histories, bronze/silver/gold tables, forecasts, MLflow runs, evaluation reports and Power BI CSVs. A separately attributed, bounded REFIT adapter exercises public-data ingestion. Simulation is labelled; it is not a real appliance accuracy study.

From the repository root, generate an editable three-page Power BI project:

```sh
uv run --project analytics python scripts/build_powerbi.py --data analytics/artifacts/powerbi
uv run --project analytics --with jsonschema==4.25.1 python scripts/validate_powerbi.py artifacts/powerbi
```

Open `artifacts/powerbi/Energy.pbip` in Power BI Desktop and refresh its local CSV imports. The generated report covers energy, coverage/missing data, and forecasts with interval status. The CSV report refreshed and rendered all three pages; a native DAX query independently matched its source totals and row counts. The operator also confirmed refresh of the separate Databricks connector variant. [Power BI instructions](powerbi/README.md).

For a portable, browser-verified energy dashboard:

```sh
uv run --project analytics python scripts/build_dashboard.py --data analytics/artifacts/powerbi --output artifacts/energy-dashboard.html
```

Open the HTML file locally. It filters source cohorts explicitly, shows energy and coverage, and displays device-specific forecast intervals without summing marginal ranges.

![Energy dashboard with synthetic data](docs/images/energy-dashboard.png)

The assistant has two distinct modes: six deterministic query intents, and an optional local Ollama model that proposes SQL. Both pass through the same read-only SQL guard. The model route is experimental; syntactically safe SQL can still answer the wrong question. [Analytics commands and evaluation](analytics/README.md).

## Repository map

| Path | Purpose |
|---|---|
| [backend](backend/README.md) | Java 21, PostgreSQL inbox/outbox, twin, authenticated REST and WebSockets |
| [simulator](simulator/README.md) | Persistent devices, telemetry receipts, fleet runner, Kafka batch export |
| [mobile](mobile/README.md) | Flutter web/Android console and persistent offline command queue |
| [analytics](analytics/README.md) | Local bronze/silver/gold, MLflow forecasts, anomaly and SQL evaluations |
| [databricks](databricks/README.md) | Delta/Unity Catalog notebooks and sequential job bundle |
| [firmware](firmware/README.md) | ESP-IDF device implementation and signed OTA profile |
| [infra](infra/README.md) | Azure Bicep and private Kubernetes backend manifests |
| [contracts](contracts/PROTOCOL.md) | Shared events, command state and transport contract |
| [docs](docs/BRIEF.md) | Business brief, architecture, decisions, validation and presentation |

## Evidence and decisions

The [validation record](docs/VALIDATION.md) separates executed tests, generated artifacts and unverified environments. The [capability matrix](docs/FEATURES.md) retains the full remaining scope with explicit acceptance conditions. The [recommendation memo](docs/RECOMMENDATION.md) preserves negative results: the synthetic forecasting challenger lost to seasonal-naive, and a SQL guard alone did not ensure correct answers from the small local model. The [six-slide presentation](docs/presentation.html) opens in a browser. Follow the [two-demo runbook](docs/DEMO.md) to present the control and energy cases.

This local deployment is a single-operator demonstration, with host ports bound to loopback. It is not an internet-facing or multi-tenant service. Read the [security boundaries](docs/SECURITY.md) before changing deployment exposure.

## Verification

```sh
uv run --project simulator --locked pytest simulator/tests -q
uv run --project analytics --locked pytest analytics/tests -q
```

Backend integration tests need a disposable PostgreSQL database; they deliberately clear its application tables. Flutter has its own analyze/test/build checks. See component READMEs and `.github/workflows/verify.yml`. The transport smoke test uses real brokers; it is separate from mocked or database-only tests.

MIT-licensed source. REFIT data retains its own attribution and licence; downloaded data, runtime credentials, model weights and build output are excluded from the repository.
