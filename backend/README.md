# Appliance backend

Java 21, Spring Boot, PostgreSQL, MQTT over verified TLS, Kafka and raw authenticated WebSocket service. This is a single-operator demonstration, not a multi-tenant platform. The shared [protocol](../contracts/PROTOCOL.md) defines JSON and topics.

## Configuration

Required: `API_TOKEN` (at least 16 characters), `SPRING_DATASOURCE_URL`, `SPRING_DATASOURCE_USERNAME`, `SPRING_DATASOURCE_PASSWORD`.

MQTT: `MQTT_ENABLED`, `MQTT_URI` (`ssl://` required), `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CA_CERT` (PEM CA bundle), `MQTT_CLIENT_ID`. The broker must grant the backend service identity subscribe access to telemetry/reported/sync and publish access to desired/receipt. Device identities require separate namespace ACLs.

Kafka: `KAFKA_ENABLED`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC` (default `appliance.telemetry.v1`). The current Kafka adapter uses the isolated local deployment network; cloud authentication requires a separate adapter/configuration change.

Other: `SERVER_PORT` (8080), `DEVICE_STALE_SECONDS` (60), `WS_AUTH_TIMEOUT_SECONDS` (5), `API_ALLOWED_ORIGINS` (comma-separated HTTP origins; localhost/127.0.0.1 ports 8090 and 18081 by default). Native clients can connect without an Origin header.

## Behaviour

Commands accept an expiry in the future, at most 24 hours away. PostgreSQL timestamp precision is microseconds. Identical UUID payloads return their existing command even after expiry; mutated payloads and stale revisions return 409. A superseded intent is no longer dispatched. If expiry follows a persisted dispatch attempt, status becomes `outcome_unknown`, not proof of non-execution.

The desired outbox commits an attempt marker before network delivery. Delivery and database completion cannot form an atomic transaction, so retries are expected. Devices must use idempotent absolute settings and revision fencing. Confirmation requires a matching device report and command ID; old reports cannot regress revision. An offline/stale snapshot exposes freshness rather than inventing a live observation.

MQTT subscriber acknowledgement follows a successful inbox transaction or durable quarantine. Application receipts are separate outbox records committed with telemetry. Identical telemetry retries requeue the receipt. Event ID and device/boot/sequence conflicts cannot change accepted payloads. Kafka events include the original durable acceptance time; consumers must deduplicate stable event IDs.

A broker acknowledgement alone does not prove platform ingestion. This service does not guarantee sensor readings survive device power loss. Dead-letter evidence is in `quarantine`; retry/error evidence is in `outbox`. Device telemetry reads are bounded to 1–1000 records and device listing to 1000. Operational database retention is a deployment policy, not automatic data deletion.

WebSocket clients authenticate in their first text frame; no updates are sent before authentication. Invalid or timed-out authentication closes the connection. A successful authentication sends `{"type":"authenticated"}`; reconnecting clients must refresh REST snapshots.

## Tests

`mvn test` runs unit tests. PostgreSQL integration tests run when `TEST_DATABASE_URL` is set, with `TEST_DATABASE_USERNAME` and `TEST_DATABASE_PASSWORD`. Use a disposable database: integration setup truncates all application tables. MQTT and Kafka are disabled in those database tests. Root software verification exercises actual transports separately.

The integration suite covers concurrent revision conflicts and idempotency, immutable telemetry, receipt replay, expiry uncertainty, report fencing, durable outbox retries, HTTP authentication/CORS and WebSocket authentication. Firmware NVS, BLE and OTA claims require the later hardware edition.
