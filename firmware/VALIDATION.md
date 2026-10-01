# Firmware build and signature evidence

Validated locally on 2026-10-01 with `espressif/idf:v5.5`, ESP-IDF 5.5, the ESP32 GNU 14.2.0 toolchain, Python 3.12.3 and Espressif `espsecure` 4.9.0. The image index digest used was `sha256:00e94c6ff8bc1f7bd22b234ff43db3f3056cb33dedac6819df9fbedbcb5c6ebb`.

The ordinary, signed-update and combined BLE/signed-update profiles compiled with version 2 persisted desired state, deadline-aware reboot restoration and durable telemetry replay. The final ordinary application was 945,504 bytes, signed application 983,028 bytes, and combined BLE/signed application 1,376,244 bytes. Each fits its 1,572,864-byte OTA slot. Credentials remained placeholders; the only certificate copied into the build was the public local broker CA. BLE proof of possession remained blank, which deliberately refuses initial provisioning until an owner configures a unique secret.

`python scripts/verify_signed_build.py` and its `--ble` variant each completed with four host cryptographic checks:

| Input | Observed host-verifier result |
| --- | --- |
| Signed image and matching public key | Accepted |
| Image with a modified byte | Rejected |
| Signed image and a different valid public key | Rejected |
| Ordinary unsigned image | Rejected |

The signed artifact SHA-256 was `5a5adfd43e0751bd9246c616bb6c400048e6ee3a2759ffb1a8c1eb2f1fe8e314`; the combined BLE/signed artifact was `d196b23a85bc8ef77b9c2ff9a62ae7b58169a68de166c973f74a979b66e03d6b`. Ignored `signature-verification.json` files in each build directory contain the machine-readable results. A new run generates a different disposable signing key and therefore a different artifact hash. Private test keys existed only in removed compiler containers.

`python scripts/test_spool.py` compiled the exact C spool core with host address and undefined-behaviour sanitizers. Nine fault suites passed: immutable replay across reopen; ambiguous append before/after commit; receipt deletion before/after commit; unknown/repeated receipts; reordered receipts and old-boot sequence preservation; full-capacity retention; payload boundaries; corrupted/truncated/unknown-version records; and duplicate persisted identities. The fault model supplies atomic durable records and does not emulate the ESP32 flash controller.

The generated configuration enabled signed application verification on update and left hardware secure boot disabled. No device was flashed, no eFuses were changed, and no electrical, NVS power-cut, Wi-Fi/BLE radio, device-side signature rejection, HTTPS update or boot rollback test was performed. BLE provisioning and NVS receipt reconciliation are implemented and compiled; their physical behavior remains unverified. Hardware acceptance cases are in [the firmware README](README.md#later-physical-evidence).
