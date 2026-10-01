# ESP32 firmware adapter

This ESP-IDF 5.5 adapter targets an ESP32 with 4 MB flash and a low-voltage GPIO demonstration. Board boot, NVS power-loss recovery, electrical output, Wi-Fi reconnection and device-side OTA rollback require physical validation. Do not connect mains wiring. Speed is a stored setpoint for a future actuator adapter, not measured fan speed.

## Ordinary build

Copy the public broker CA from `.runtime/certs/ca.crt` to `firmware/main/ca_cert.pem`. This build input is ignored by Git. Do not copy the broker private key. From `firmware/`:

```powershell
docker run --rm -v "${PWD}:/project" -w /project espressif/idf:v5.5 idf.py build
```

Defaults contain empty Wi-Fi and MQTT passwords and a localhost broker address. They compile but cannot operate a remote board. Before a later hardware run, configure the device ID, unique broker password, reachable TLS hostname and appropriate GPIO with `idf.py menuconfig`. Register that device through the backend API and grant its own namespace ACLs. Never commit generated `sdkconfig` files or binaries containing credentials.

TLS requires a trusted CA and matching broker hostname; plaintext MQTT URIs and retained actuation messages are rejected. Sync is sent after desired-topic subscription acknowledgement.

## Persistence and state

NVS stores one versioned desired-state record including its deadline, committing before output application. On reboot the GPIO starts off. After clock synchronization, the saved setting is restored only if its deadline is still valid. Expired power intent remains stored but requires a fresh command; selected speed and revision fencing survive. This avoids applying an intent that expired after a power cut between persistence and actuation. It is a deliberate reboot policy, not a universal appliance policy. An NVS recovery error never automatically erases revision fencing. This first hardware release uses record schema2; unknown older layouts fail closed.

Commands require synchronized UTC, matching identity, a newer revision or an identical current command, valid setpoints and an unexpired deadline. This adapter supports 32-bit revisions. It has no toggle/pulse commands. Reports have their own monotonic sequence separate from telemetry.

Wi-Fi, clock and broker diagnostics each have a bounded 60-second wait. A pending OTA image is marked valid only after those checks. Failure attempts rollback only for an image pending verification; other failed boots restart with a diagnostic. Network failure can reject an otherwise functional update. Review this conservative policy during hardware testing.

Energy is a setpoint estimate labelled `estimated`, with `setpoint_model_no_energy_sensor`. It applies the current setpoint across the sampling interval, not calibrated measurement.

## Durable telemetry and receipts

After startup diagnostics, every ten-second sample is committed to a dedicated NVS partition before MQTT publication. The spool retains up to 64 immutable JSON events (about 10 minutes 40 seconds at this cadence). Each event carries its original UUID, boot UUID, sequence, timestamp and counter through disconnects and reboots. A new boot starts a new UUID and counter; replay never rewrites an old event as new data. Replay sends up to eight events per second in round-robin order.

Only an `accepted` application receipt on this device's ACL-protected receipt topic retires the matching UUID. MQTT PUBACK does not delete data. Unknown and repeated receipts are harmless. An ambiguous NVS commit or corrupt/unknown record fails closed and requires a restart/recovery; the adapter never erases the partition automatically. The storage core uses an explicit little-endian versioned encoding and CRC, not a compiler-dependent struct layout.

A full spool preserves existing unacknowledged data and skips new samples. Sampling sequence continues, and the next retained sample includes `telemetry_spool_capacity_exceeded`; logs also record the overflow. The overflow flag itself is volatile across a reboot, but the boot change remains visible and persisted events are retained. Sampling starts only after initial Wi-Fi, UTC and broker diagnostics: this is bounded outage retention, not uninterrupted logging from power-on. Flash endurance and physical power-cut recovery still need a board test.

The partition table adds `telemetry` at `0x320000`, using previously unused flash. Install this partition table during the first attended flash. An OTA application update does not update a partition table; devices with the earlier layout need a separate attended migration before this image.

Run the same C spool core under host address/undefined-behaviour sanitizers:

```powershell
docker run --rm -v "${PWD}:/project" -w /project espressif/idf:v5.5 python scripts/test_spool.py
```

The fault-injection storage model exercises cuts before/after append and receipt commits, reboot replay, immutable payloads, out-of-order/duplicate receipts, full capacity, size boundaries and corruption. It tests algorithmic recovery under atomic-record storage assumptions; it does not simulate the ESP32 flash controller.

## BLE Wi-Fi provisioning

The optional `sdkconfig.ble.defaults` profile enables the official ESP-IDF BLE provisioning manager. On an unprovisioned board it advertises `APPL_<MAC suffix>` for an attended five-minute setup window, using Security 1 (X25519/AES-CTR and proof of possession). Set a unique `APPLIANCE_PROVISION_POP` of at least 16 characters through local menuconfig and supply it to the owner out of band. Blank or short values refuse provisioning. No credential, proof or QR payload is logged. Provision with the Espressif **ESP BLE Provisioning** app; this release's Flutter console does not contain a provisioning client.

Wi-Fi credentials persist in the ESP-IDF Wi-Fi NVS namespace. On subsequent boots the stored station configuration is used and BLE memory is released. A wrong password, pairing, provisioning timeout and recovery require physical radio tests. There is deliberately no remote factory reset that could destroy desired-state revision fencing or unacknowledged telemetry. Broker identity, broker password and CA remain local build/provisioning inputs separate from Wi-Fi provisioning.

```powershell
docker run --rm -v "${PWD}:/project" -w /project espressif/idf:v5.5 idf.py -B build-ble -D SDKCONFIG=/project/sdkconfig.ble -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.ble.defaults' build
```

## Signed-update software checks

Ordinary builds refuse OTA even when an HTTPS URL is configured. `sdkconfig.signed.defaults` enables signed-app verification without hardware secure boot. No secure-boot or anti-rollback eFuses are programmed. It does not defend against physical replacement of the bootloader.

After the ordinary build:

```powershell
docker run --rm -v "${PWD}:/project" -w /project espressif/idf:v5.5 python scripts/verify_signed_build.py
```

The script generates throwaway ECDSA keys only inside the compiler container, builds `build-signed/appliance_device.bin`, then exercises Espressif's host verifier with a valid image, modified image, wrong key and unsigned image. Its ignored JSON evidence records results and artifact hash. These are host cryptographic checks, not execution of device OTA or proof of rollback.

Add `--ble` to the verification script to build and check the combined BLE/signed profile in `build-signed-ble`. Both profiles retain the same A/B slot and spool partition layout.

For real update versions, store a stable signing key outside the checkout and mount it at `/keys/ota-signing-key.pem`. Never deploy the script's disposable keys to a fleet. Each image embeds its trusted public key, so key rotation requires a migration plan.

OTA requires HTTPS. Public certificate roots are the default; `APPLIANCE_OTA_USE_BROKER_CA` explicitly selects the local broker CA for an attended local experiment. The updater rejects a different project or the already installed version before downloading the full image. Increment `PROJECT_VER` in `CMakeLists.txt` for an intentional update. A/B slots cover application images; bootloader and partition-table OTA are outside scope.

Keep the NVS layout compatible with the previous firmware. A/B slots do not make destructive settings migrations reversible.

## Later physical evidence

Record hashes and serial logs for: power interruptions around NVS writes and application receipts, full spool/replay, BLE provisioning and Wi-Fi reconnection, successful/failed OTA boot, invalid signature, interrupted download, stale commands, invalid broker certificate and settings compatibility after rollback. Calibrated sensing and actuator feedback require additional hardware.

References: [ESP-IDF 5.5 NVS](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/storage/nvs_flash.html), [OTA and signed-update configuration](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/system/ota.html), [ESP-IDF 5.5 signing configuration](https://github.com/espressif/esp-idf/blob/v5.5/components/bootloader/Kconfig.projbuild).
