# Fleet performance experiment

The local simulator exercised **1,000 devices and 3,000 generated events**. All 3,000 received application receipts, with zero dropped events and zero pending spool rows at the recorded endpoint. The run generated three synchronized bursts at a ten-second interval and completed in 68.938 seconds including the receipt drain. This establishes short-run completion, not sustained capacity or production latency.

| Workload | Events | Accepted by endpoint | p50 receipt, s | p95 receipt, s | Wall time including drain, s |
|---|---:|---:|---:|---:|---:|
| 100 devices / 2 s, serial publisher | 1,500 | 403 | 46.031 | 51.500 | 60.500 |
| 100 devices / 2 s, bounded workers | 1,500 | 1,500 | 1.203 | 16.437 | 52.375 |
| 1,000 devices / 10 s, bounded workers | 3,000 | 3,000 | 24.375 | 36.094 | 68.938 |

The first row's latency distribution includes only its 403 observed receipts; 1,097 events remained pending when that run stopped. It is not an all-event latency estimate. Later backend processing drained its accepted workload. No delivery-loss claim follows from that short endpoint.

The diagnostic comparison exposed synchronous outbox delivery as a constraint. The original worker sent 25 records then waited 250 ms, with every MQTT/Kafka acknowledgement blocking the next send. The revised publisher has eight bounded workers, each claiming immediately before sending up to 32 rows, then waits 100 ms between cycles. Claims use PostgreSQL row locking and a durable lease; retries and stable event identity remain necessary. Concurrent-claim and locked-head-row regressions passed.

These were shared-host runs on Windows with Docker Linux containers, not a controlled throughput study. Firmware compilation and other project verification overlapped parts of the diagnostic comparison. The before/after values should not be quoted as an isolated speedup caused solely by one change. Container memory caps were PostgreSQL 512 MiB, Mosquitto 128 MiB, Kafka 768 MiB and backend 768 MiB. Backend Java heap was capped at 384 MiB. Simulator process CPU time for the 1,000-device timed window was 14.734 seconds; no scheduled ticks were missed.

Receipt latency measures first publish attempt to durable application receipt, using monotonic time. It includes transport/backend queuing but excludes device registration and initial connection setup. It is not command-actuation latency. Device accepted counters persist across runs; the experiment subtracts initial counters. The final drain is included in duration. The 1,000-device p95 of 36.094 seconds is too high to support an interactive telemetry SLA.

Reproduce from the repository root after bootstrap and service readiness:

```sh
uv run --project simulator python scripts/bootstrap.py --devices 1000
docker compose kill -s HUP mosquitto
uv run --project simulator python scripts/with_env.py uv run --project simulator appliance-simulator run --count 1000 --interval 10 --duration 30 --drain-seconds 90 --state-dir .runtime/benchmark-new --stats artifacts/fleet-1000.json
```

Use a fresh state directory or retain initial counters for comparison. Avoid another process with the same device IDs. A fresh filename alone does not reset persistent device state. For a fuller capacity study, stagger device schedules, measure ingestion/outbox lag separately, run a sustained soak, inject broker/database outages, and sample per-process CPU/memory throughout. Do not infer those results from this burst test.

The bounded telemetry API query orders by `(received_at DESC, event_id)` for one device and limits results to at most 1,000. Its `(device_id, received_at DESC, event_id)` index matches that access path; a captured `EXPLAIN ANALYZE` plan accompanies the local artifacts. Operational retention and database growth still require a deployment policy.


## Bounded Azure run

A separate run on 1 October 2026 used a temporary Southeast Asia `Standard_B2as_v2` Linux VM (2 vCPU, 8 GiB) with the same four-container stack. One hundred simulated devices generated 30 scheduled ticks at ten-second intervals: 3,000 events over 301.190 seconds including final drain, with no missed ticks. All 3,000 received durable application receipts; dropped and pending counts were zero. Receipt p50 was 1.145 seconds, p95 2.533 seconds and maximum 4.105 seconds across 3,000 samples.

Two fresh Kafka consumer groups each exported 3,001 unique events: the fleet plus one transport-smoke event. Their complete logical event maps matched, and their event-ID sets equalled the PostgreSQL-backed API result. Batch checks verified content hashes and row counts. This is transport reconciliation; the energy/late-data oracle experiments use separate datasets.

Twenty-nine Docker snapshots were collected approximately every ten seconds across acceptance. Observed maximum memory was 241.0 MiB for the backend, 66.96 MiB for PostgreSQL, 440.6 MiB for Kafka and 6.957 MiB for Mosquitto. These are sampled container values, not continuous peak or whole-VM measurements. Docker CPU percentages can exceed 100% when multiple cores are used. The simulator recorded 5.684 CPU seconds.

The smaller Azure fleet and longer generation window differ from the local 1,000-device burst. Their latencies do not establish a controlled cloud/local speedup or a production SLO. Longer soaks, failure injection, ingestion/outbox lag and resource saturation remain open. See the [sanitized receipt](../infra/evidence/azure-smoke.json) and [infrastructure validation](../infra/VALIDATION.md) for source, environment, cleanup and cost boundaries.
