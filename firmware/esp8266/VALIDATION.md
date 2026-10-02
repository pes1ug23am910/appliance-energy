# ESP8266 validation

Recorded on 2026-10-02 with ESP8266_RTOS_SDK v3.4 (`89a3f254b63819035f65d9c5dcdae8864f1a6a8a`) and Espressif Xtensa LX106 GCC 8.4.0 `esp-2020r3-49-gd5524c1`. The pinned MQTT component is `01594bf118ae502b5a0ead040446f2be75d26223`, with the repository patch applied.

The physical result is **partial**: a USB-only NodeMCU V3 passed identification, backup and flash verification, Wi-Fi/DHCP, SNTP and the numeric JSON startup check. A later run using a new saved Wi-Fi profile delivered old-boot backlog and fresh estimated telemetry through authenticated TLS/MQTT to the cloud API. GPIO remained disabled. Logical ON/40% and final OFF/0% commands converged at revisions 1 and 2 despite three identical retries per command, and conflicting requests were rejected. A controlled reboot produced a fresh boot identity and reconverged to revision 1. A controlled 35.026-second broker outage recovered three events generated while the broker was stopped. The board also rejected separately tested expired and not-yet-valid server certificates. Durable receipt retirement, extended outage/power-cut behavior and sustained runtime memory checks remain in progress.

## Build records

The following are distinct artifacts, not interchangeable footprint measurements:

| Recorded build | Application bytes | Application SHA-256 |
| --- | ---: | --- |
| Earlier certificate-date-corrected inert build | 623,920 | `7cb118b52db49c1ea79f3cb820396265ab0c35717122f027bb9f430a02ff9065` |
| SUBACK-patched inert build, 13:15 UTC | 624,016 | `91010c9db4b4f5b65efb5b319c781c10757b382966e529c640d49912247a2da3` |
| Full-format JSON hardware build, 13:28 UTC | 694,832 | `c7c74bb853789c56e269c821fc3cc201185af1c39bc66017b7b0d7a0385ab5b5` |
| Full-format JSON inert build, 13:45 UTC | 694,768 | `1e81fb73d9166b53c9239e046a8c1f69068e1c4c27f999932070f57387786151` |
| Phone-network hardware build, 14:05 UTC | 694,832 | `79c943817a5e806b3dce6cfb661fad947e842e1bd51800f976c2d11f57954709` |

The SUBACK-patched and full-format builds used toolchain image ID `sha256:f6f0cfb7ddf35ab747dba6eb2353e443fa75a1d043657e10ddfaf4a37dc1b7b7`. The full-format hardware build's `main/main.c` SHA-256 was `89d3dc2c9dc2a205f6f0a3c7d1c9ca58978776db8cb92128e3edb1aa28efa5c3`. Its build manifest and subsequent flash-verification receipt agree on the application, bootloader and partition images. The application hash identifies a private configured bench image; it is not a downloadable release or a credential-free reproducibility target.

All five builds linked Wi-Fi, TLS, MQTT, durable spool and desired-state functions. The inert builds used explicit placeholder credentials and a reserved `.invalid` broker, rather than blank credentials that could permit dead-code elimination. The latest hardware build additionally verified full numeric formatting, both mbedTLS time/date options, dynamic TLS buffers, 4 MiB flash and disabled GPIO output. The final inert receipt independently verifies full-format linked symbols, the two certificate-time options, disabled GPIO and unchanged hardware configuration; that compile check did not exercise the board.

The full-format hardware build log reports 13,420 bytes static DRAM and 27,759 bytes static IRAM, with 84,884 / 21,393 bytes unallocated. The inert build logs reported the same static DRAM/IRAM values, including the final full-format build. These are linker measurements; unallocated static memory is not a measurement of runtime free heap.

The configured factory slot is 1,572,864 bytes, telemetry NVS is 256 KiB, and the main/MQTT task stacks are each 6,144 bytes. TLS record capacities are 16 KiB incoming and 4 KiB outgoing with dynamic buffers. Actual handshake memory headroom remains unverified.

## Host checks

Earlier recorded runs passed four desired-state suites and nine shared-spool suites under AddressSanitizer and UndefinedBehaviorSanitizer:

- Desired-state checks covered exact duplicates without rewriting, stale/conflicting revisions, clock/deadline rejection, the JSON-safe revision range, interrupted commits before and after persistence, fail-closed reopening, every record-byte corruption, truncation and malformed UUIDs.
- Shared-spool checks covered immutable reboot replay, uncertain append/receipt commits, matching/unknown/repeated/reordered receipts, full capacity without eviction, payload boundaries, corrupt/truncated/unknown records and duplicate persisted identities. ESP32 and ESP8266 use the same portable C implementation.

The updated `scripts/test_mqtt_retain.py` passed against the exact rebuilt toolchain image under ASAN/UBSAN. It compiles the production upstream delivery function, receiver, processor, request validator and packet parsers, with transport/outbox stubs and unrelated PUBLISH paths stubbed for the SUBACK cases. Its checks cover:

- Original-header RETAIN across continuation-buffer overwrite and consecutive messages; failed reads and malformed initial headers do not complete delivery.
- Successful SUBACK grants 0, 1 and 2; denied `0x80`, reserved codes, absent/extra grant bytes, a zero packet ID and invalid header flags cannot report success or consume the pending request.
- Every split point, one-byte reads and adjacent complete packets; truncation waits for completion, while a subsequent transport failure never acknowledges the request.
- Unknown/duplicate IDs and a successful first acknowledgement followed by a denied second acknowledgement cannot fabricate two successful subscriptions.
- A negative control runs the same rejection assertion against the original pinned receiver and confirms that it fails on the old false-success behavior.

The host binaries use non-PIE linking and bounded execution. An earlier sanitizer run entered a repeated signal-handler failure; its test container was stopped. The final non-PIE run passed with the default sanitizer settings. These are parser/transport-boundary checks, not TLS, broker ACL or physical-device tests. A successful SUBACK is subscription readiness evidence; delivery still needs an observed desired message or application receipt.

## Numeric JSON and allocation checks

The SDK's nano formatting configuration was insufficient for cJSON's numeric conversion path. Current defaults select full Newlib formatting with `CONFIG_NEWLIB_NANO_FORMAT=n`, and a compile-time guard rejects a nano-enabled generated configuration. Existing configurations require an explicit update; changing defaults alone does not override an old selection.

Before Wi-Fi startup, `json_numeric_self_test()` serializes and parses integer `1`, fractional energy `2 * 10 / 3600`, and revision `2^53 - 1`, then checks the values. JSON object/member creation and serialization are checked so allocation or formatter failures stop the device before a partial document can be persisted or published.

The repository harness, [`scripts/test_json.py`](scripts/test_json.py), extracts the actual JSON helper functions and compiles them with the pinned SDK's cJSON under ASAN/UBSAN. The recorded local run passed all 16 numeric allocation-failure positions and all 9 quality-flag allocation-failure positions without leaked allocations or partial documents. An injected formatter error was identified as serialization failure. Allocation ownership accounting instrumented the helper's `free(text)` calls; this checks host error handling, not the target Newlib implementation. The successful physical startup roundtrip below supplies separate target execution evidence.

The `esp8266` job in [the verification workflow](../../.github/workflows/verify.yml) is configured to build the pinned toolchain, cross-compile an inert image and run the MQTT and JSON regressions. The local results above are recorded; execution of this new hosted CI job remains pending.

## Physical bring-up

The board was identified as an ESP8266EX with 4 MiB flash through its CH340 serial interface. The complete original flash image was backed up and verified before the first project installation. Its backup SHA-256 is `4db4798ebe739122d1e209ad431cdf9febf00ee33b63a838c2dba73cebc0d4a2`. Project bootloader, partition-table and application writes were verified against their images. The first full-format 694,832-byte application was flashed and readback-verified at 13:30 UTC without an NVS erase. The separately configured network image was flashed and verified at 14:07 UTC; its application hash is recorded above. GPIO remained disabled, with USB as the only board connection.

An earlier private-hotspot test obtained DHCP but failed the 60-second SNTP gate for both a hostname and directly addressed public server. The PC independently obtained public NTP replies. That earlier result did not reach MQTT.

A separate network-only diagnostic subsequently joined the saved Wi-Fi network, obtained DHCP and reported plausible SNTP UTC. Its evidence explicitly excludes TLS, MQTT, application receipts, storage recovery and actuation. SNTP is unauthenticated UDP; plausible time is not authenticated time.

The full-format project image then independently passed its startup numeric roundtrip and received a clock update. The captured startup line reported 87,424 free-heap bytes and 3,344 free main-task stack bytes. These are early-startup observations, not minimum heap or MQTT-task stack measurements during TLS. The subsequent TCP connection attempts on that network returned `errno 113`; this is a connection failure observation, not proof of a certificate or broker-authentication problem.

The later project image, built for a new saved Wi-Fi profile, passed the same startup checks, obtained DHCP/SNTP and delivered telemetry through the temporary cloud broker's TLS-only listener with its unique device credential. The captured startup measurements were 86,336 free-heap bytes and 3,344 free main-task stack bytes. The API verifier at 14:11 UTC confirmed an online device at desired/reported revision 0, 64 events from an earlier boot and 23 events from the current boot, including fresh arrivals. It checked event/boot UUIDs, sequences, immutable overlapping records, `source_kind: estimated`, `setpoint_model_no_energy_sensor` and `gpio_output_disabled`. This proves board-to-backend delivery with GPIO disabled, not physical energy measurement or switching.

An initial freshness check failed while the old backlog was arriving; the later strict check passed after fresh events appeared. Both results are retained. API observations alone do not prove durable deletion after application receipts or a completely drained spool. This later run succeeded after the saved Wi-Fi profile changed; the earlier failure cause has not been isolated.

The logical-command check submitted ON with a 40% setpoint from expected revision 0. Three identical retries of the same UUID produced one desired revision; reusing the UUID with changed content and submitting a stale expected revision both returned HTTP 409. The command receipt was confirmed, and desired/reported state converged to revision 1 with the requested values. GPIO remained disabled throughout. This validates command identity and logical reconciliation, not an actuator transition count or a physical effect.

After a controlled reboot, the API verifier at 14:21 UTC observed a fresh boot UUID and new telemetry, verified that overlapping historical records were unchanged, and confirmed desired/reported revision 1 with ON/40%. Backend synchronization can contribute to this reconvergence, so the check does not isolate restoration from the board's flash. It does not establish complete spool replay or arbitrary power-cut durability.

A controlled broker stop lasted 35.025616 seconds. After restart, the verifier identified three events with generation times inside the outage and receipt times after recovery; no simulated events were injected. Fresh telemetry resumed, and the cleanup check verified that the broker was running. This establishes observed delivery of a short outage backlog, not complete spool drainage or durable receipt-driven deletion.

Build manifests, flash/readback receipts, configuration checks and raw serial logs are retained privately. Configured binaries, original flash backups, credentials and workstation paths are excluded from the published source.

The temporary Azure resource group was verified deleted at 14:35 UTC after diagnostics were captured. Follow-up checks verified removal of the task network watcher, zero remaining Azure resources, and termination of the bench watchdog and tunnel. An empty helper resource group was retained because its creation by this task could not be established. The board was then flashed and readback-verified with a private parking image whose serial startup reported no network startup, project GPIO access or project-storage access. Project NVS/spool partitions were not erased, and the original flash backup was retained. The tested network image is therefore a recorded bench artifact, not the board's current running application.

## Certificate-date configuration audit

Earlier compile and board images used the SDK default with `CONFIG_MBEDTLS_HAVE_TIME_DATE` disabled. They configured CA and hostname verification but did not enforce certificate validity dates; the application clock gate alone did not enable that check. Current defaults and compile-time guards require both mbedTLS time support and certificate-date verification. Private generated-configuration checks independently enforce the same requirements.

The earlier corrected 623,968-byte hardware image was flashed and readback-verified; it predates the SUBACK and numeric-format changes above. A host preprocessor check rejected all eight invalid time/date flag combinations and accepted the enabled pair. Current builds pass those configuration checks. The later network configuration supplies a positive TLS baseline. Two bounded negative tests then replaced only the server leaf's validity window, preserving its key, issuer, subject, SAN and other extensions. The PC independently rejected the expired leaf with verification code 10 and the future leaf with code 9. During the corresponding test windows, the board serial log recorded mbedTLS `-0x2700` with the specific reasons `The certificate validity has expired` and `The certificate validity starts in the future`. The shared serial capture SHA-256 is `91a72c0aae7252b19a14b89ad97ebec20440691300d674a208b553332acaef38`.

The original leaf was restored and independently verified after each case. A strict API observation also confirmed fresh board telemetry after the expired-certificate case. After the future-certificate case, the final OFF/0% command also passed the same three-retry and HTTP 409 conflict checks, converged desired/reported state to revision 2, and was followed by fresh telemetry. The command receipt captured 196 rows; a separate final API snapshot at 14:31 UTC captured 203 rows with revision 2, OFF/0% and online status at that moment. This confirms board recovery after both valid-certificate restorations, without asserting a continuously available service. Helper receipts record PC verification separately from the reviewed board serial evidence; serial growth alone was not treated as certificate rejection. These results apply to this image and bench clock, and do not establish resilience to a hostile time source.

## Isolated lakehouse check

The saved 203-event board snapshot was loaded into a separate Databricks schema with `source_kind: estimated` and GPIO-disabled provenance retained. Bronze, silver, unique event/boot-sequence identities and summed gold reading counts all matched 203. Quarantine, invalid-interval and gap counts were zero. The one daily gold row contained 5.44043333 Wh of setpoint-estimated energy over 2,005 covered seconds (2.320602% of the day): 200 covered intervals, two reboot resets and one first reading. This is a short bench observation, not measured appliance consumption or a full-day energy estimate.

All 14 gold cells matched the independently computed DuckDB row with absolute numeric tolerance `1e-7`. Replaying the Databricks ingestion/model job left the checked results unchanged. Unity Catalog recorded 12 lineage edges across four inspected gold columns. The existing synthetic reference remained unchanged at 142 daily rows, 40,322 readings and 221,277.67265636 Wh.

Forecast execution was disabled for this sparse partial-day board cohort; no board forecasting accuracy is claimed. The SQL warehouse was verified stopped after the check.

## Remaining physical validation

The initial TLS/MQTT connection, old-boot backlog delivery, logical command reconciliation, controlled-reboot reconvergence and short broker-outage backlog delivery passed. Durable application-receipt retirement, extended outage behavior, real power-cut durability and sustained heap/stack headroom remain in progress. GPIO polarity and physical switching remain unverified. Energy is a labelled setpoint estimate, not measured consumption; speed is not PWM. This adapter has no BLE provisioning or OTA/rollback implementation. ESP32 signed A/B OTA and BLE results are separate evidence and do not establish ESP8266 hardware behavior.
