# Appliance protocol version 1

This is the shared contract for the local software edition. Cloud and hardware adapters must preserve the same semantics.

## Identity and time

Use UTC ISO-8601 timestamps with offsets. Identifiers are restricted to ASCII letters, digits, underscore and hyphen (1-64 chars), except command UUIDs. Device state revisions are nonnegative monotonic integers. Operational API access uses an environment-supplied bearer token for the single demonstration operator; do not claim multi-tenant isolation unless implemented and tested.

Operational event and observation timestamps must lie between 1970-01-01 UTC and server UTC plus 300 seconds. Invalid messages are quarantined before timestamp SQL conversion. Within one boot, the increasing reported-state sequence orders observations even if the device wall clock regresses. Across boots, observation time guards against older snapshots. Report sequence is independent of telemetry sequence.

## HTTP API

All /api routes require Authorization: Bearer <API_TOKEN>. Health endpoints carry no sensitive state. JSON uses snake_case.

- GET /api/devices -> array of device snapshots.
- POST /api/devices {device_id,name} -> device snapshot (new device starts at revision 0).
- GET /api/devices/{device_id} -> snapshot.
- POST /api/devices/{device_id}/commands -> command receipt.
- GET /api/commands/{command_id} -> receipt.
- GET /api/devices/{device_id}/telemetry?limit=100 -> latest accepted readings, bounded to 1000.

Command request: {command_id: UUID, expected_revision: integer, desired: {power: boolean, speed_percent: integer 0..100}, expires_at: UTC timestamp}.

Receipt: {command_id,device_id,revision,status,desired,expires_at,created_at}. Status: accepted, awaiting_device, confirmed, expired, superseded, outcome_unknown, rejected. A repeated ID and equal payload returns the same logical command. Changed payload or stale expected_revision returns HTTP 409. Validate expiry on acceptance and on delivery/application. A timeout never proves no physical effect.

`confirmed` means the current desired revision was observed with matching command identity and state. A matching later report can resolve `outcome_unknown` after dispatch expiry. It does not prove the physical action occurred before its deadline; expiry bounds dispatch/application rather than receipt arrival.

Snapshot: {device_id,name,desired_revision,reported_revision,desired:{power,speed_percent},reported:{power,speed_percent},last_seen,status}. Freshness is derived explicitly; a stored report is not always a current observation.

## MQTT

Broker TLS endpoint 8883; reject invalid certificates. Devices use unique credentials restricted to their own namespace. Backend has a separate service credential. QoS 1, no retained actuation commands. Durable DB acceptance and application-level telemetry receipt are stronger than broker acknowledgement.

- devices/{device_id}/desired: {command_id,device_id,revision,desired,expires_at}
- devices/{device_id}/reported: {device_id,boot_id,sequence,revision,power,speed_percent,observed_at,firmware_version,command_id?}
- devices/{device_id}/telemetry: event below.
- devices/{device_id}/receipt: {event_id,status:'accepted'} after durable telemetry commit; simulator retries outstanding events.
- devices/{device_id}/sync: {device_id,boot_id}; backend resends current non-expired desired state and simulator republishes its report.

The backend subscribes to reported, telemetry and sync. Retrying absolute setpoints is safe; stale revisions cannot regress state. Duplicate equal revisions report current state. Do not expose toggle/pulse operations.

The firmware's reboot policy starts the output off, restores persisted settings only after clock sync while their stored deadline remains valid, and requires a fresh command for expired power intent. The software simulator models durable settings and event receipts, not electrical behaviour; its saved setpoint survives a process restart.

## Telemetry event

{schema_version:1,event_id:UUID,device_id,boot_id:UUID,sequence:integer,event_time:UTC timestamp,source_kind:'simulated'|'measured'|'estimated'|'public_dataset',power_w:number>=0,energy_wh_total:number>=0,firmware_version:string,quality_flags:array of strings}.

Backend adds received_at. Stable identity is event_id, with a uniqueness check on (device_id,boot_id,sequence). Identical duplicate is a no-op; conflicting identity is quarantined/rejected with evidence. Payload is immutable. Sequence and cumulative counter reset with a new boot_id. Missing intervals remain missing. Simulated energy is never labelled measured.

## Export and analytics

Outbox publishes accepted telemetry to Kafka topic appliance.telemetry.v1, key device_id, value normalized event including received_at. Consumer creates immutable JSONL batches plus SHA-256 manifest with row_count, event IDs hash, time bounds and schema version. Replays may duplicate physical deliveries; logical energy must not double-count. Consumer offset commits only after atomic batch/manifest publication.

Analytics accepts the normalized JSONL contract from a file path so it runs without Kafka or Databricks. Tables use bronze_events, silver_telemetry, quarantine, gold_device_hourly, gold_device_daily, gold_quality, forecast_daily, anomaly_daily. Column and transformation provenance stays explicit.

## Live UI

Raw WebSocket /ws: first frame {type:'authenticate',token:API_TOKEN}. Server refuses all state before authentication and closes unauthenticated clients after a bounded timeout. Messages {type:'device_updated',device: snapshot} or {type:'command_updated',command:receipt}. On reconnect, refresh HTTP snapshots; WebSocket delivery alone is not authoritative. Native and browser Flutter clients must work without a token in the URL.
