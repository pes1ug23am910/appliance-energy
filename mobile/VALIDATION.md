# Mobile application validation

Validation performed on 2026-10-01 using Flutter 3.47.5 and Dart 3.13.4. Flutter Web was exercised on Windows and Chrome 154.0.8037.59. Android was built in Linux CI and its native SQLite plugin was exercised on an Android API 35 x86_64 emulator. Physical phones and iOS/Windows application packages remain unverified.

## Executed checks

| Command | Observed result |
| --- | --- |
| flutter analyze | No issues found |
| flutter test --timeout 40s | 14 tests passed |
| flutter build web --release --no-web-resources-cdn | Release build succeeded, local rendering resources bundled |
| .venv-browser/Scripts/python.exe tool/browser_smoke.py | Passed against the actual Java API, MQTT simulator and browser SQLite |
| .venv-browser/Scripts/python.exe tool/capture_ui.py | Fleet/device screenshots captured and inspected at 1440x1100 and 430x932 |
| flutter test integration_test/native_store_test.dart -d emulator-5554 | Native Android persistence test passed in CI |
| flutter build apk --debug --target-platform android-arm64,android-x64 | Android debug package built in CI for ARM64 and x86_64 |

The 14 tests cover durable dispatch intent and response loss; immutable retry payload; 409 conflict without rebasing; expiry before dispatch; attempted-command uncertainty and late receipt recovery; one unresolved command per device; server-origin isolation; SQLite close/reopen; bearer headers; report freshness; server URL validation; real WebSocket first-frame authentication and coalescing of 100 events into one HTTP repair; token-form validation; stale dashboard state; and explicit review after a revision changes. Some tests cover more than one related assertion.

## Real browser recovery

The browser blocked backend API requests, saved an absolute command, reloaded the page, re-entered the token and recovered the same command from SQLite/IndexedDB. After restoring API access, the backend accepted the original ID and the running simulator confirmed it.

- Command: a77e63d0-540f-4620-a78f-71dc65de575c.
- Expected revision: 3; confirmed device revision: 4.
- Original ID survived page reload and reconnect; one dispatch attempt was displayed.
- No page errors and no token in request URLs.
- Tokens were not written into screenshots, SQLite or source.
- JSON result: ../artifacts/mobile-browser-smoke.json.
- An earlier run with no simulator preserved an awaiting-device outcome and subsequently expired to outcome_unknown; its evidence is retained separately rather than reported as a successful actuation.

Browser request observation included the two loopback services and an antivirus-injected Kaspersky origin. The application itself bundles rendering/SQLite resources locally; this does not claim isolation from software installed on the host.

## Inspected views

Original application screenshots contain only simulated device data:

- [Fleet](../docs/images/mobile-fleet.png): searchable devices, fresh reports and desired/reported revisions.
- [Device](../docs/images/mobile-device.png): confirmed state and source-labelled telemetry.
- [Restored offline queue](../docs/images/mobile-restored-queue.png): same local command after full reload.
- [Confirmed recovered command](../docs/images/mobile-confirmed-command.png): server and simulator confirmation.
- [Phone-width layout](../docs/images/mobile-narrow-device.png): responsive stacked state cards and controls.

## Android emulator and package

The Android job passed for source commit `a22d4b95` in [verification run 36901022460](https://github.com/pes1ug23am910/appliance-energy/actions/runs/36901022460), using Ubuntu 24.04, Java 21, Android API 35 AOSP x86_64 with KVM, and NDK 28.2.13676358. The application compiles/targets API 36 and supports API 24 or later. The same job then built the ARM64/x86_64 debug APK.

The integration test used the actual Android sqflite and path-provider plugins, wrote an uncertain command, closed and reopened the platform database, checked the original ID and immutable payload, verified server-origin isolation and revisions above the 32-bit range, then persisted and recovered a confirmed receipt. It did not contact the Java backend or control an appliance. The existing browser recovery test supplies the separate end-to-end API/simulator evidence.

This is a debug-signed sideload package, not a Play Store release or physical-phone test. Android internet permission is declared, cleartext is restricted to localhost/127.0.0.1, and Android backup is disabled. Remote backend origins require HTTPS; `adb reverse tcp:18080 tcp:18080` supports an attended local demonstration. The Windows host did not execute an Android emulator because Windows Hypervisor Platform was disabled; no host reboot or virtualization change was made.

The Windows host also built the ARM64/x86_64 debug APK on 2026-10-01 (125,983,653 bytes; SHA-256 `95dc65702b19d10ec6692da08d86b0ca4e7ba210023b3a5d43b77d2d0287cf25`). Android build-tools 36.0.0 `apksigner verify --verbose` verified its APK Signature Scheme v2 signature. This artifact is ignored by Git and uses a local debug certificate; it was not installed on a physical phone.

The application remains a single operator prototype. It does not establish multi-tenant authorization, physical actuation guarantees, hardware validation, or iOS/Windows application builds.
