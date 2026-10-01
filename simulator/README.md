# Simulator and telemetry exporter

Each device owns a SQLite database containing its absolute setpoint and a bounded pending-event spool. A process restart creates a new boot epoch while preserving pending identities and desired state. Settings commit before the simulator reports them. This models software behaviour; it cannot prove physical relay behaviour.

Run commands from the repository root after bootstrap and Compose startup:

```sh
uv run --project simulator python scripts/with_env.py uv run --project simulator appliance-simulator run --count 100 --interval 2 --duration 60 --drain-seconds 30 --stats artifacts/fleet.json
uv run --project simulator appliance-simulator export --once
```

Use `--start-index` to select a zero-based credential offset. Do not run two simulators for the same device identity concurrently: MQTT client IDs and SQLite files deliberately belong to one device. For larger fleets, rerun `scripts/bootstrap.py --devices N`, then reload broker authentication with `docker compose kill -s HUP mosquitto` before starting new identities.

TLS validates the local CA and host name. Device credentials can access only their own MQTT namespace. QoS 1 provides transport retries, not exactly-once physical actuation. An application receipt means the backend has durably accepted that event. The spool deletes an event only after that receipt; disconnects, restarts and lost receipts can cause identical retransmission.

The spool holds up to 10,000 pending events per device. At capacity it records a dropped-event count. Counter energy continues advancing, so later analysis can expose missing observation intervals. It never silently represents a missing interval as observed. A reported-state sequence is independent of telemetry sequence, so repeated reports remain ordered.

Statistics include generated events, initial/final accepted and dropped counters, pending events, missed ticks, process CPU time and receipt latency. Accepted/dropped counters persist across runs: subtract initial values before comparing a particular run. Receipt latency measures first publish attempt to application receipt; retained samples are bounded to the latest 10,000 per device and are not physical command latency. Provisioning time is excluded from the timed generation window. The configured receipt drain window is included.

The exporter atomically publishes a directory containing `events.jsonl` and a manifest before committing Kafka offsets. A crash between publication and offset commit permits duplicate files/events; ingestion must deduplicate them. Manifests record event/time/hash/offset evidence. No exactly-once Kafka-to-filesystem transaction is claimed.

`--once` waits for assignment and three empty polls (about nine seconds) before exit. Use `--group` and `--output` to isolate a replay experiment. A new group can read retained topic history; Kafka retention still bounds that history. The local Kafka listener uses loopback and the private Compose network, without cloud SASL/TLS configuration.
