# Mobile application validation

Validation performed on 2026-10-01 using Flutter 3.47.5, Dart 3.13.4, Windows, and installed Chrome 154.0.8037.59. The application target is Flutter Web; native SQLite is covered by tests, while native app packaging/device builds remain unverified.

## Executed checks

| Command | Observed result |
| --- | --- |
| flutter analyze | No issues found |
| flutter test --timeout 40s | 14 tests passed |
| flutter build web --release --no-web-resources-cdn | Release build succeeded, local rendering resources bundled |
| .venv-browser/Scripts/python.exe tool/browser_smoke.py | Passed against the actual Java API, MQTT simulator and browser SQLite |
| .venv-browser/Scripts/python.exe tool/capture_ui.py | Fleet/device screenshots captured and inspected at 1440x1100 and 430x932 |

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

The browser demo is a single operator prototype. It does not establish multi-tenant authorization, physical actuation guarantees, hardware validation or Android/iOS/Windows application builds.
