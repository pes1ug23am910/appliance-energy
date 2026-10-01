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

Energy is a setpoint estimate labelled `estimated`, with `setpoint_model_no_energy_sensor` and `no_durable_telemetry_spool` flags. It applies the current setpoint across the sampling interval, not calibrated measurement. There is no durable telemetry spool or application-receipt reconciliation. Sequence gaps expose disconnected sampling loss. The Python simulator's durable-spool results do not transfer to this adapter.

## Signed-update software checks

Ordinary builds refuse OTA even when an HTTPS URL is configured. `sdkconfig.signed.defaults` enables signed-app verification without hardware secure boot. No secure-boot or anti-rollback eFuses are programmed. It does not defend against physical replacement of the bootloader.

After the ordinary build:

```powershell
docker run --rm -v "${PWD}:/project" -w /project espressif/idf:v5.5 python scripts/verify_signed_build.py
```

The script generates throwaway ECDSA keys only inside the compiler container, builds `build-signed/appliance_device.bin`, then exercises Espressif's host verifier with a valid image, modified image, wrong key and unsigned image. Its ignored JSON evidence records results and artifact hash. These are host cryptographic checks, not execution of device OTA or proof of rollback.

For real update versions, store a stable signing key outside the checkout and mount it at `/keys/ota-signing-key.pem`. Never deploy the script's disposable keys to a fleet. Each image embeds its trusted public key, so key rotation requires a migration plan.

OTA requires HTTPS. Public certificate roots are the default; `APPLIANCE_OTA_USE_BROKER_CA` explicitly selects the local broker CA for an attended local experiment. The updater rejects a different project or the already installed version before downloading the full image. Increment `PROJECT_VER` in `CMakeLists.txt` for an intentional update. A/B slots cover application images; bootloader and partition-table OTA are outside scope.

Keep the NVS layout compatible with the previous firmware. A/B slots do not make destructive settings migrations reversible.

## Later physical evidence

Record hashes and serial logs for: power interruptions around NVS writes, successful/failed OTA boot, invalid signature, interrupted download, stale commands, invalid broker certificate and settings compatibility after rollback. BLE provisioning is explicitly unimplemented. Calibrated sensing, actuator feedback and a durable device spool are later increments.

References: [ESP-IDF 5.5 NVS](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/storage/nvs_flash.html), [OTA and signed-update configuration](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/system/ota.html), [ESP-IDF 5.5 signing configuration](https://github.com/espressif/esp-idf/blob/v5.5/components/bootloader/Kconfig.projbuild).
