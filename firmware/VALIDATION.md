# Firmware build and signature evidence

Validated locally on **2026-10-02** with `espressif/idf:v5.5`, ESP-IDF 5.5, the ESP32 GNU 14.2.0 toolchain, Python 3.12.3 and Espressif `espsecure` 4.9.0. The image index digest was `sha256:00e94c6ff8bc1f7bd22b234ff43db3f3056cb33dedac6819df9fbedbcb5c6ebb`.

## Corrected configuration and builds

All four profiles rebuilt successfully with both `CONFIG_MBEDTLS_HAVE_TIME=y` and `CONFIG_MBEDTLS_HAVE_TIME_DATE=y` verified in their generated configurations. Each image includes version 2 persisted desired state, deadline-aware reboot restoration and durable telemetry replay, and fits its 1,572,864-byte application slot.

| Profile | Application bytes | SHA-256 |
| --- | ---: | --- |
| Ordinary | 946,032 | `1555c0f8909cc8b9550d513dfc6665d32e2a8046fcd9c0c4b9c8940020610e30` |
| BLE provisioning | 1,373,392 | `fd84abfd9e191a8bf9d33ab4aed28b941d6f3afbd9a41f37d11960b5fad39a8e` |
| Signed update | 983,028 | `f5696c211ab8b919244ca1dea0db19d7e7dcc6c0a9c6f464ed2c65738b032a1e` |
| BLE + signed update | 1,376,244 | `77de84335db39025d06e560ae599533e763cb6dc2189ba2c39e31fb78b444573` |

The rebuild changed only these two TLS settings in the existing ignored profile configurations. Credentials remained placeholders; the only certificate input was the public local broker CA. BLE proof of possession remained blank, deliberately refusing initial provisioning until an owner configures a unique secret. Binary sizes and hashes describe software artifacts, not measured device memory headroom.

`python scripts/test_tls_config.py` passed inside the same toolchain container. It verifies that both firmware targets explicitly enable the two TLS options in their defaults, rejects all eight missing/disabled option combinations through the C preprocessor, and accepts the fully enabled pair. The shared guard is included by both adapter translation units, so cached configurations with date checks disabled cannot silently compile. This check also runs in the Python CI job.

## Host signature checks

`python scripts/verify_signed_build.py` and its `--ble` variant each completed successfully with freshly generated container-only ECDSA test keys:

| Input | Signed profile | BLE/signed profile |
| --- | --- | --- |
| Signed image and matching public key | Accepted | Accepted |
| Image with a modified byte | Rejected | Rejected |
| Signed image and a different valid public key | Rejected | Rejected |
| Ordinary unsigned image | Rejected | Rejected |

Ignored `signature-verification.json` files in each signed build directory record these checks and artifact hashes. New runs generate different disposable keys and therefore different signed artifact hashes. Private test keys existed only in removed compiler containers. Signed application verification on update was enabled; hardware secure boot remained disabled.

## Storage checks

The unchanged portable spool core has nine passing host AddressSanitizer/UndefinedBehaviorSanitizer suites: immutable replay across reopen; ambiguous append before/after commit; receipt deletion before/after commit; unknown/repeated receipts; reordered receipts and old-boot sequence preservation; full-capacity retention; payload boundaries; corrupted/truncated/unknown-version records; and duplicate persisted identities. The fault model supplies atomic durable records and does not emulate the ESP32 flash controller. These are separate host checks, not physical power-cut evidence.

## Certificate-validation scope

An audit found that the earlier ESP32 generated profiles had `CONFIG_MBEDTLS_HAVE_TIME_DATE` disabled. Those earlier builds configured broker CA/hostname checks and HTTPS OTA trust roots, but did not enforce X.509 validity dates. Their startup clock gate did not enable this separate mbedTLS option. Current defaults, the compile-time guard, and the four successful rebuilds above correct that configuration gap. Expired/not-yet-valid certificate rejection tests against running firmware remain pending.

No ESP32 device was flashed, no eFuses were changed, and no electrical, physical NVS power-cut, Wi-Fi/BLE radio, device-side signature rejection, HTTPS update or boot rollback test was performed. BLE provisioning and NVS receipt reconciliation are implemented and compiled; their physical behavior remains unverified. Hardware acceptance cases are in [the firmware README](README.md#later-physical-evidence). Separate ESP8266 board evidence does not establish ESP32 behavior.
