# ESP8266 software adapter

This separate C target brings the existing device protocol to an ESP8266 NodeMCU/Wemos-class board. It preserves the ESP32 implementation in `../main`. The supplied profile is for a **4 MB flash board**, but the physical board's flash size and pin routing must be identified before any flashing. GPIO output is disabled by default.

## Implemented behavior

- Wi-Fi station mode; MQTT 3.1.1 over TLS using an embedded broker CA certificate, hostname verification and unique per-device credentials. SNTP must establish a plausible UTC clock before certificate/deadline use.
- Absolute desired power/speed settings, command UUID, deadline and revision persisted as a versioned 64-byte, CRC-protected NVS record before applying the logical output. Revisions support the JSON-safe integer range through `2^53 - 1`. Equal revisions require an exactly matching command; stale/conflicting revisions are rejected. A failed commit is ambiguous: stop and reopen after reboot rather than accept another command.
- Reboot starts output off. A fatal storage/transport fault latches the device off until restart, preventing a concurrent command from re-energizing it. Only a still-unexpired saved setting can be restored after clock synchronization. Expiry bounds applying an intent, not how long a successfully applied setpoint stays on.
- The exact shared portable C telemetry spool from the ESP32 target: 64 immutable events, up to 767 payload bytes each, CRC-protected durable records; only an `accepted` application receipt for the exact event ID retires a record. MQTT PUBACK only frees a transport window. Reboot replays old boot IDs, timestamps, counters and sequences unchanged.
- One outstanding QoS1 publication bounds the transport queue. Uncertain publish failures retain that window; acknowledgement timeout reboots while preserving the flash spool. Reconnect requests current desired state after subscription acknowledgement.
- New samples every 10 seconds. A full spool retains unacknowledged events, skips new samples with a log message and marks the next accepted sample with `telemetry_spool_capacity_exceeded`. This overflow flag is volatile across reboot; it is not an exact persisted loss counter. Sixty-four entries hold roughly 10.7 minutes of samples when no application receipts arrive.
- Energy remains a labelled setpoint estimate (`source_kind: estimated`), not a meter reading. Speed is a model setting, not PWM or fan-speed feedback. With GPIO disabled, reports describe the logical device state and telemetry includes `gpio_output_disabled`.

## Reproducible software build

The legacy official [ESP8266_RTOS_SDK v3.4](https://github.com/espressif/ESP8266_RTOS_SDK/tree/v3.4) is pinned to `89a3f254b63819035f65d9c5dcdae8864f1a6a8a`, with Espressif's Xtensa LX106 GCC 8.4.0 compiler archive verified by SHA-256. The Docker image isolates its Python 3.8 requirements from modern ESP32 tooling. It is a legacy demonstration target, not a claim of current vendor security maintenance.

From the repository root:

```sh
docker build -t appliance-esp8266-toolchain:3.4 firmware/esp8266
# Copy only the public broker CA certificate; never copy its private key.
cp .runtime/certs/ca.crt firmware/esp8266/main/ca_cert.pem
docker run --rm -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 python scripts/build_compile.py
# Optional attended configuration for a future device test:
docker run --rm -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 make defconfig
docker run --rm -it -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 make menuconfig
docker run --rm -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 make -j2 all
```

The compile check uses explicit inert SSID/password values and a reserved `.invalid` broker hostname in an isolated ignored configuration. This keeps networking reachable during linking; blank credentials deliberately stop startup and otherwise let the compiler remove those paths. It checks that Wi-Fi, TLS, MQTT and persistence symbols are present in the linked image. It never flashes hardware or connects to a broker.

For a future attended hardware test, set the device ID, Wi-Fi SSID/password, TLS broker URI and unique device password under **ESP8266 appliance settings**. The broker hostname must match its certificate and resolve/reach the board's Wi-Fi network; `localhost` is only an inert build default. Generated `sdkconfig`, CA input, binaries and local configuration are ignored by Git. Build outputs contain configured credentials; keep them private. No flashing is performed by these commands.

The **NTP server hostname or IPv4 address** setting (`CONFIG_APPLIANCE_NTP_SERVER`) defaults to `pool.ntp.org`. Set a reachable time server when the device network restricts DNS or outbound NTP; a numeric IPv4 address bypasses hostname resolution. Startup logs the DHCP DNS address, available heap, clock updates and progress every 15 seconds. These diagnostics do not perform a separate blocking DNS lookup. If a plausible clock is unavailable after the 60-second synchronization window, startup fails closed before restoring saved output or starting MQTT. Certificate verification and command expiry remain enforced.

The original pinned MQTT component does not expose incoming RETAIN. `patches/mqtt-retain.patch` adds the event field and captures the original fixed-header bit before continuation reads overwrite the receive buffer. The build checks the exact upstream commit and applies only this patch. It also checks signed transport-read failures before converting the result to an unsigned length; otherwise the legacy code could treat a negative read as a continuation payload. The adapter rejects retained and fragmented desired/receipt messages. A fresh sync retries legitimate desired state after reconnect.

## Software tests

```sh
docker run --rm -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 python scripts/test_desired.py
docker run --rm -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 python scripts/test_mqtt_retain.py
docker run --rm -v "${PWD}:/project" appliance-esp8266-toolchain:3.4 python ../scripts/test_spool.py
```

The desired-state and shared-spool tests compile the production C with AddressSanitizer and UndefinedBehaviorSanitizer. The MQTT regression test compiles the actual patched upstream delivery function with a stub transport/parser to exercise retained-bit propagation across fragments and consecutive messages. It does not simulate a TLS connection. See [validation](VALIDATION.md) for executed evidence.

## Boundaries and hardware follow-up

ESP8266 has no BLE. This target uses local build configuration, not BLE provisioning. OTA is deliberately absent: the ESP8266 SDK does not provide the ESP32 pending-image health-confirmation/automatic-rollback API. The ESP32 signed A/B OTA and BLE profiles remain separate. No secure boot, flash encryption, hostile-clock protection or production fleet security is claimed here.

Dynamic TLS receive/transmit buffers are enabled with the SDK's 16 KiB incoming / 4 KiB outgoing record limits; certificate and hostname validation remain enabled. Actual peak heap and task-stack headroom still require a board run.

The partition profile allocates 24 KiB for configuration NVS, 1.5 MiB for one factory application and 256 KiB for telemetry NVS. Settings and telemetry are never auto-erased on storage errors. Do not reuse an ESP32 partition image or perform an unattended partition-table migration.

Physical acceptance requires a known data-capable micro-USB cable, verified serial enumeration, read-only chip/flash identification, then an attended board-specific configuration and flash. The compiler cannot verify TLS heap headroom, radio connectivity, actual flash commit/power cuts, boot-pin behavior or physical output. The normal route is the board's own USB serial interface. An UNO is not a drop-in 3.3 V USB-UART adapter: model-dependent routing, level conversion and contention with the NodeMCU's onboard CH340C must be resolved before any interconnection. No UNO wiring or mains-appliance connection is required for this software edition.

