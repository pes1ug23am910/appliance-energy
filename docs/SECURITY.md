# Security boundaries

The software edition assumes one trusted operator on one development machine. Compose host ports bind to `127.0.0.1`; this is not an internet deployment. The API bearer token grants operator-wide access and is not tenant isolation. Browser queues are separated by server origin, not user identity.

MQTT requires verified TLS and unique device credentials. Broker ACLs restrict devices to their own topics. The backend is a trusted service identity across device topics. Keep `.env`, `.runtime`, the local CA private key and device passwords outside Git. Regenerating only `.env` while retaining the PostgreSQL volume does not rotate its database password.

Local REST/WebSocket and Kafka use loopback/private-network transport. A remote deployment needs HTTPS, Kafka authentication/encryption, secret provisioning and rotation, authorization by tenant/device, audit/retention policy and backup recovery tests. Do not expose these local ports publicly by changing bind addresses alone.

The SQL interface only permits approved reads and denies external table functions and mutation. It returns bounded results and uses query interruption. The experimental model runs locally through an explicitly supplied Ollama URL; no external provider is required. SQL safety checks do not establish answer accuracy.

ESP32 OTA is opt-in under a signed update profile. Host-side signature verification and successful compilation do not prove power-cut rollback, secure boot, flash encryption, anti-rollback fuses or safe electrical operation. Firmware does not actuate mains voltage in this software edition.

All checked-in examples use synthetic identifiers or intentionally public test credentials. A test database is disposable: integration tests truncate application tables. Do not point those tests at a retained environment.
