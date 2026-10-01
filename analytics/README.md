# Local analytics

Python 3.12, DuckDB, NumPy/pandas, MLflow tracking and SQLGlot. `uv.lock` pins the dependency graph. There are no paid calls in the default workflow.

```powershell
cd analytics
uv sync --locked --python 3.12
uv run --locked pytest -q
uv run --locked python scripts/run_demo.py
```

The demo creates `data/reference.jsonl`, a DuckDB database, MLflow runs under `artifacts/forecast/mlruns`, evaluated forecasts, anomaly candidates, CSVs under `artifacts/powerbi`, and `artifacts/demo-evidence.json`. It checks that replay leaves energy unchanged and the assistant evaluation passes. Generated data, databases, environments and artifacts should remain out of Git.

## Protocol and ingestion

```powershell
uv run --locked python scripts/verify_live_batches.py
```

Run this from `analytics` after completing the repository-root simulator/export commands. It reads actual batches under `../data/batches/`, verifies their manifests, ingests them into a separate `data/live.duckdb`, checks replay invariance and exports `artifacts/live-powerbi`. The recorded batch count describes one snapshot; later exports can increase it. For a separately supplied normalized JSONL file, use `appliance-analytics --db data/live.duckdb ingest <path-to-file> --max-gap-seconds 120`.

Input is normalized protocol v1 JSONL, including `received_at`; see `../contracts/PROTOCOL.md`. UTC offsets are required. Bronze records preserve physical source hash, filename, line and raw evidence. Silver keeps the first accepted immutable event; equal event IDs/payloads are no-ops. Changed event payloads and collisions on `(device_id,boot_id,sequence)` are quarantined. `received_at` is delivery metadata and excluded from device-payload identity. File hashes prevent repeated physical ingestion. Ingestion and gold rebuilding occur in one transaction. Late observations recompute affected results, including previously missing intervals.

`energy_wh` sums counter differences only between consecutive sequences of the same boot, with increasing event time and a gap within the configured maximum. First readings and reboot transitions invent no energy. Counter regression or invalid ordering produces an invalid interval. Long/missing-sequence intervals contribute counter deltas to `unallocated_energy_wh`, not to covered energy. Covered intervals crossing UTC hours are allocated proportionally in time; this is an explicit within-interval allocation assumption. Missing samples stay missing. Gold reports coverage independently. Use the same gap policy when rerunning a database; changing the option deliberately recomputes its semantics.

Energy aggregates are stored as decimal Wh with eight fractional places so replay sums are deterministic; this arithmetic precision is not a sensor-accuracy claim. Every aggregate retains `source_kind`. `measured`, `estimated`, `simulated` and `public_dataset` are separate cohorts. No currency cost, carbon or intervention saving is inferred without an explicit tariff/emissions/causal model. Quality flags and raw provenance must accompany exported claims.

## Data and forecasting

```powershell
uv run appliance-analytics fixture --output data\reference.jsonl --days 70 --devices 2
uv run appliance-analytics --db data\reference.duckdb ingest data\reference.jsonl --max-gap-seconds 600
uv run appliance-analytics --db data\reference.duckdb forecast --artifacts artifacts\forecast
uv run appliance-analytics --db data\reference.duckdb anomalies
```

The reproducible reference fixture samples every five minutes; its labels identify deliberately injected energy spikes. Forecasts require 56 consecutive days at >=80% coverage. A 14-day calibration segment chooses a research candidate between weekly seasonal-naive and ridge regression on trend/day-of-week. The following 14 days are an expanding-origin, one-day holdout; each subsequent origin can use earlier observed holdout values. Candidate selection does not use holdout error. The dashboard's `forecast_daily` deliberately retains the **seasonal-naive reference baseline**, with `model=seasonal_naive` and `forecast-policy.json` recording `release_status=baseline_reference`. `artifacts/forecast/candidate-forecast-daily.csv` retains separate unpromoted candidate forecasts and their `calibration_selected_model` metadata. The consumer table schema stays unchanged. Neither output is validated for measured-device decisions; promotion requires independent evidence. Metrics include MAE, RMSE, MASE when its denominator is nonzero, observed interval coverage and width. Ninety-percent target intervals use absolute calibration residuals; coverage under drift is not guaranteed. Days 2ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“7 use explicitly provisional intervals, because one-day evaluation does not validate multi-day coverage. MLflow records parameters, metrics, holdout predictions, input series and model specification. Batch forecasts need no model-serving endpoint.

Anomaly scores compare seasonal residuals with past residual median/MAD. Alert precision/recall are reported only for simulated days with explicit `injected_anomaly` or `evaluation_label_normal` flags. Unlabelled and real-data alerts are candidates, not diagnosed faults. Simulator accuracy cannot establish accuracy on real appliances.

## Public REFIT sample

```powershell
uv run appliance-analytics refit-fetch --output data\refit-sample.csv --rows 1000
uv run appliance-analytics refit-adapt data\refit-sample.csv --output data\refit.jsonl
uv run appliance-analytics --db data\refit.duckdb ingest data\refit.jsonl --max-gap-seconds 16
```

The optional fetch streams at most 10,000 requested rows and 4 MB from the public [cleaned REFIT record](https://zenodo.org/records/5063428), writing URL/hash attribution provenance. [The raw dataset source](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/) specifies CC BY 4.0 and requests citation of Murray/Stankovic/Stankovic, [Scientific Data 2017](https://doi.org/10.1038/sdata.2016.122). The adapter reads a local selected CSV with `Unix` and a chosen power column. It estimates a cumulative energy counter using left-held power; `energy_counter_estimated_from_power` marks that distinction. Gaps >16 seconds and nonmonotonic time start a new segment, so no energy is invented across them. The bounded sample validates ingestion, not forecasting accuracy or population representativeness. Historical UK homes are not an Indian commercial-site benchmark.

## Read-only assistant

```powershell
uv run appliance-analytics --db data\reference.duckdb ask --question "total energy"
uv run appliance-analytics --db data\reference.duckdb evaluate --fixtures evals\sql_cases.json --output artifacts\assistant-eval.json
```

The default planner is deterministic and supports six exact intents: `total energy`, `daily energy`, `highest energy devices`, `data quality`, `forecast`, `anomalies`. Other questions abstain. This is a tested supported-intent interface, not a claim of LLM reasoning. The optional `--planner-url` calls a JSON service that can wrap a model: POST `{question,allowed_tables,instruction}`, response `{sql:string|null}`; `ANALYTICS_PLANNER_TOKEN` is read only from the environment. It sends table schemas and the question, not raw telemetry. Provider output uses the same guard. No provider call is made unless selected explicitly, and no hosted provider quality/cost is claimed.

A concrete local LLM route uses Ollama's `/api/chat` endpoint. Install/start Ollama and obtain a suitable model separately; the adapter never downloads a model or invokes a paid API. Then run:

```powershell
uv run appliance-analytics --db data\reference.duckdb ask --ollama-url http://127.0.0.1:11434 --ollama-model qwen2.5-coder:1.5b --question "How much covered energy in kWh is there in total for each source kind?"
uv run appliance-analytics --db data\reference.duckdb evaluate --ollama-url http://127.0.0.1:11434 --ollama-model qwen2.5-coder:1.5b --fixtures evals\provider_cases.json --output artifacts\ollama-eval.json
```

The adapter passes only schemas and the question to a local HTTP endpoint, requests bounded JSON output with temperature zero, and validates generated SQL through the identical guard. The provider evaluation contains six intents and paraphrases plus unsupported/attack questions. Its independent expected-result queries compare actual rows (numeric tolerance 0.00051 and relative tolerance 0.00001), required ordering, and refusals. Wrong numerical answers are counted separately from execution failures and abstention. All failures remain visible; the evaluator exits nonzero when any case fails. Actual model-run results must be read from the generated report; mocked transport unit tests establish plumbing and guards only. Template baseline and model results are separate evidence.

SQLGlot allows a single SELECT over one authorized gold table, with limited aggregate functions. External/table functions, non-gold tables, joins, CTEs, subqueries, multiple statements and writes are rejected. A copied gold snapshot runs in a DuckDB connection with external access disabled, UTC timezone, 128 MB memory, one thread, a timeout and enforced row limit. Smaller explicit limits retain their top-N meaning. Malformed provider output, unavailable tables, incompatible queries and interruptions return structured errors; errors never count as successful refusals. Results include SQL, table provenance and snapshot freshness. Evaluation tests refusal/safety and reconciles an answered energy total against a separate pandas oracle. User authentication and tenant isolation belong to the surrounding application; this CLI makes no multi-tenant claim.

The Databricks adapter has separate [cloud execution evidence](../databricks/VALIDATION.md), including a comparison against this local daily gold oracle. Local DuckDB tests alone do not establish cloud behavior. Native Power BI evidence is recorded [separately](../powerbi/VALIDATION.md); hosted refresh remains untested.

## Verified results, 1 October 2026

The final local suite passed **45 tests**. The full deterministic demonstration ingested **40,322 synthetic events**, preserved exactly **221,277.67265636 Wh** on replay, and passed **17/17** template/safety/reconciliation checks. Its CSV contains 142 device-day rows, including two partial endpoint days; forecasting uses the 70 sufficiently covered days per device. Template checks use exact supported intents and are a different suite from the natural-language provider comparison.

Both local models were run against the unchanged **18-case provider suite** and the same system prompt. Twelve cases ask answerable questions; six ask unsupported or unsafe questions. Scores enforce the declared result columns, units and ordering, including projection errors as mismatches.

| Local provider | Answerable results correct | Unsupported/attack cases safely handled | Executed answer mismatches | Model abstentions | Guard rejections |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen 2.5 Coder 1.5B | 3/12 | 6/6 | 5 | 0 | 10 |
| Qwen 3.5 9B | 11/12 | 6/6 | 1 | 6 | 0 |

The smaller model invented tables, confused Wh/kWh, omitted required result columns, and omitted an anomaly filter. Its six safety successes came from the guard, not model refusal. The challenger retained one unit error: daily consumption returned Wh instead of the configured kWh. Both original reports preserve failures. The challenger used the supported `think:false` inference control so the 512-token JSON answer budget did not get consumed by reasoning; the first model has no thinking capability. Temperature, context size, output cap, prompt and questions otherwise stayed fixed. Concurrent local services/tests shared compute, so these runs are not speed benchmarks. These finite results do not establish general reliability; deterministic templates remain the default and generated SQL/results remain reviewable.

After the SQL guard fixes and baseline forecast export, `uv run --locked python scripts/replay_provider_reports.py` re-executed every saved candidate against the current database and independent expected queries. All 36 case outcomes remained unchanged. `artifacts/provider-guard-replay.json` hashes the original reports and records this check. This was saved-SQL replay, not a fresh model run; the original reports were not overwritten.

The forecast challenger also failed to improve the untouched holdout: fixture-1 ridge MAE was **390.37 Wh** versus seasonal-naive **148.26 Wh**; fixture-2 was **444.30** versus **167.46 Wh**. Selection used calibration only, and the worse holdout remains reported. Anomaly precision **0.75** and recall **1.0** apply only to explicitly labelled synthetic injections.

Actual local transport ingestion verified **91** completed MQTT-to-Kafka export manifests and accepted **1,619** unique simulated observations with zero quarantines. Replaying all 91 batches left identity counts, time bounds and **1.68874305 Wh** unchanged. Reproduce this independent path with `uv run --locked python scripts/verify_live_batches.py`; it writes a separate `data/live.duckdb`, `artifacts/live-ingestion-evidence.json` and `artifacts/live-powerbi` CSVs. The transport is real local software; the device observations remain simulated.

The checked-in [result summary](results/local-verification.json) contains model digests and exact scope. Full generated reports live under `artifacts`; those files and the databases are excluded from source control. The locked runtime dependency audit checked **47 packages**, found no known vulnerabilities and skipped none at this date. [VALIDATION.md](VALIDATION.md) records the local checks and links to the separately executed cloud evidence.
