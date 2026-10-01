# Firmware build and signature evidence

Validated locally on 2026-10-01 with `espressif/idf:v5.5`, ESP-IDF 5.5, the ESP32 GNU 14.2.0 toolchain, Python 3.12.3 and Espressif `espsecure` 4.9.0. The image index digest used was `sha256:00e94c6ff8bc1f7bd22b234ff43db3f3056cb33dedac6819df9fbedbcb5c6ebb`.

Both profiles compiled after adding the version 2 persisted record and deadline-aware reboot restoration. The ordinary application was 942,960 bytes; the signed application was 983,028 bytes. Each fits its 1,572,864-byte OTA slot. Credentials remained placeholders; the only certificate copied into the build was the public local broker CA.

`python scripts/verify_signed_build.py` completed with four host cryptographic checks:

| Input | Observed host-verifier result |
| --- | --- |
| Signed image and matching public key | Accepted |
| Image with a modified byte | Rejected |
| Signed image and a different valid public key | Rejected |
| Ordinary unsigned image | Rejected |

The signed artifact SHA-256 was `40367aea839a0be68bd52424ea9c544e4470094aeeade17a112a5b3600164c17`. The ignored `build-signed/signature-verification.json` contains the corresponding machine-readable result. A new run generates a different disposable signing key and therefore a different artifact hash. Private test keys existed only in the removed compiler container.

The generated configuration enabled signed application verification on update and left hardware secure boot disabled. No device was flashed, no eFuses were changed, and no electrical, NVS power-cut, Wi-Fi, device-side signature rejection, HTTPS update or boot rollback test was performed. Compilation and host signature rejection are the evidence here; physical acceptance tests remain in [the firmware README](README.md#later-physical-evidence). BLE provisioning and durable hardware telemetry reconciliation remain unimplemented.
