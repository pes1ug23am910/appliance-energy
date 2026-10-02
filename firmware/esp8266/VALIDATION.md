# ESP8266 validation

Validated on 2026-10-02 with the official ESP8266_RTOS_SDK v3.4 (`89a3f254b63819035f65d9c5dcdae8864f1a6a8a`) and Espressif Xtensa LX106 GCC 8.4.0 `esp-2020r3-49-gd5524c1`, isolated in the repository's Docker build environment.

## Cross-compilation

`python scripts/build_compile.py` completed successfully. It uses explicit inert SSID/password values and a reserved `.invalid` broker, with GPIO output disabled. It also verified that Wi-Fi, TLS, MQTT, durable spool and desired-state functions were present in the linked ELF. A blank-credential build is not used as full-feature footprint evidence because its startup guard permits dead-code elimination.

| Measurement | Result |
| --- | --- |
| Application binary | 623,472 bytes |
| Application SHA-256 | `ec20ac82bf9950742387c4f06f06c78847f7696ccde9452392d36ae09eb10077` |
| Factory application slot | 1,572,864 bytes |
| Static DRAM (`.data` + `.bss`) | 13,420 bytes |
| Static IRAM | 27,759 bytes |
| Linker-reported unallocated DRAM / IRAM | 84,884 / 21,393 bytes |
| Configured flash size | 4 MiB; matches the separately identified bench board |
| Telemetry NVS partition | 256 KiB |
| Application / MQTT task stack configuration | 6,144 / 6,144 bytes |
| TLS record capacities | 16 KiB incoming / 4 KiB outgoing; dynamic buffers enabled |

These are build measurements, not runtime free-heap or stack-watermark measurements. TLS handshakes, network buffers, FreeRTOS tasks and NVS caches allocate memory at runtime. The binary is a private compile artifact with inert configuration; no publishable hardware image or production credential is implied.

## Host checks

All 15 fault/regression suites passed under AddressSanitizer and UndefinedBehaviorSanitizer in the same Docker environment:

- **4 desired-state suites:** exact duplicate without rewriting; stale/conflicting revisions; expired/missing clock rejection; revisions above 32 bits and the JSON-safe maximum; interrupted commit before and after persistence; fail-closed behavior until reopen; all 64 individual byte corruptions; truncated records; malformed UUID rejection.
- **2 MQTT delivery suites:** original-header RETAIN survives continuation-buffer overwrite and resets between messages; failed transport reads and malformed initial headers do not complete delivery. These tests compile the actual pinned, patched upstream delivery function with stubbed transport/parser boundaries. The negative-read case exposed and now guards against an unsigned-length conversion bug in the legacy implementation.
- **9 shared telemetry-spool suites:** immutable payload/reboot replay; uncertain append and receipt commits; matching/unknown/repeated/reordered receipts; full capacity without eviction; payload boundaries; corrupt/truncated/unknown versions; duplicate persisted identities. The same C implementation is used by both ESP8266 and ESP32 targets.

Build review additionally checked that both subscriptions must be acknowledged before publication, fatal errors latch the output off against concurrent commands, and a failed publish cannot silently reopen the one-message transport window.

## First board bring-up

A USB-only NodeMCU V3 was identified as an ESP8266EX with 4 MiB flash through its CH340 serial interface. The complete original flash image was backed up and verified before installing the project. Project bootloader, partition table and application writes were verified against their images. GPIO output remained disabled, with no external wiring.

The board joined a private 2.4 GHz hotspot on channel 1 and obtained a DHCP address. A diagnostic build reported 60,488 bytes of free heap before time synchronization. This is a startup observation, not peak TLS headroom or a task-stack watermark.

Time synchronization did not complete within the 60-second window when using either a public NTP hostname or a directly addressed public NTP server. The PC independently received public NTP replies. The device stopped before starting MQTT, preserving the clock requirement for certificate verification and command expiry. Board-side TLS, telemetry delivery, command confirmation and outage/reboot recovery remain **in progress**. A configurable NTP endpoint supports further testing on networks with restricted time-service reachability; certificate checks have not been relaxed.

The final source passed full network-enabled inert compilation and all 15 existing host suites. An initial parallel run stalled in the desired-state and MQTT test binaries; those two containers were stopped, and bounded sequential retries passed without production-code changes. The hardware configuration, CA input and binary were preserved during these checks. Hardware credentials, configured binaries, flash backup and workstation logs are kept outside the published source.

## Remaining physical validation

Real power-cut durability, completed broker/TLS handshakes, sustained runtime memory headroom and GPIO polarity remain unverified. Energy is estimated from setpoints, not measured. GPIO is disabled by default; speed is not PWM. This adapter has no BLE provisioning or OTA/rollback implementation. ESP32 signed A/B OTA and BLE checks are separate evidence and do not establish ESP8266 hardware behavior.
