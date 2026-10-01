# Appliance Energy operator app

Flutter web console for the API in ../contracts/PROTOCOL.md. It shows device state, report freshness, energy samples and a persistent command history. Commands set absolute power and fan speed; a local queue entry never represents device confirmation.

## Run

Validated toolchain: Flutter 3.47.5 / Dart 3.13.4. Install Flutter from the [official SDK archive](https://docs.flutter.dev/install/archive) and verify the archive checksum. No Android SDK is required for the web profile.

From this directory:

    $env:PATH = "$env:USERPROFILE\tools\flutter\bin;$env:PATH"
    flutter pub get
    dart run sqflite_common_ffi_web:setup
    flutter run -d web-server --web-hostname 127.0.0.1 --web-port 8090

Open http://127.0.0.1:8090. Enter the backend origin (normally http://127.0.0.1:18080) and its operator token. The backend must allow the UI origin through CORS, including the Authorization and Content-Type headers. Remote origins require HTTPS; loopback HTTP is supported for this local edition.

The token stays in memory and must be entered after a reload. It is never persisted, included in a query string or passed to a third-party service. Commands and snapshots are retained in SQLite, partitioned by exact server origin. This is a single demonstration operator interface; shared browser profiles are not an authorization boundary.

Use a fixed browser origin and port: browser storage belongs to that origin. Clearing site data removes the local queue. The UI host must remain available to load the application; once loaded, backend disconnection does not prevent local queuing. Browser storage restrictions can prevent startup, in which case the app fails visibly rather than silently falling back to a volatile queue.

## Reliability contract

- SQLite commits command ID, expected revision, absolute setpoint and expiry before any dispatch.
- A retry first checks the command receipt and then reuses the original payload and ID.
- A lost response is delivery_unknown; it never becomes assumed success or failure.
- Conflict and validation rejection remain visible. Neither the queue nor the editor silently rebases an expected revision.
- Expiry stops dispatch. An attempted command without confirmation remains expired_unconfirmed, and receipt reconciliation continues.
- One unresolved command per device limits conflicting local intent. A later command after a terminal result uses an explicitly reviewed snapshot.
- The WebSocket authenticates in its first frame. Live events trigger authoritative HTTP snapshot and receipt repair; five-second polling covers missed messages. No token is placed in the socket URL.
- A report older than 30 seconds, missing, or more than five seconds in the future is labelled stale/unknown.
- Telemetry preserves source kind and individual sample timestamps. The boot counter is not presented as total energy across device restarts.

The storage adapters use SQLite FFI for native targets and SQLite WASM with IndexedDB persistence for the browser. Web is the built and exercised application target. Native storage is exercised by tests; Android/iOS/Windows app packaging and device builds are separate work. The web adapter is an experimental upstream package, so browser persistence requires an application-level reload check as well as the native SQLite tests.

## Verify and build

    flutter analyze
    flutter test --timeout 40s
    dart run sqflite_common_ffi_web:setup
    flutter build web --release --no-web-resources-cdn
    python -m http.server 8090 --bind 127.0.0.1 --directory build/web

Tests cover response loss without a duplicate logical dispatch, same-payload retry, conflicts, local expiry, uncertain outcomes, SQLite close/reopen, origin isolation, bearer transport, WebSocket first-frame authentication with snapshot repair, stale reports, credential form validation, and explicit revision review in the editor.

The setup command generates web/sqlite3.wasm and web/sqflite_sw.js; these build inputs are ignored in Git and must be generated in clean environments. pubspec.lock pins the app dependencies. See upstream [SQLite web setup](https://pub.dev/packages/sqflite_common_ffi_web) and [WebSocket channel API](https://pub.dev/packages/web_socket_channel).

The current UI reports raw recent telemetry. Governed aggregation, forecast intervals and the business energy dashboard belong to the analytics demo.


## Real-browser recovery check

With the local backend, this static UI and the simulator for device-0001 running:

    python -m venv .venv-browser
    .\.venv-browser\Scripts\python.exe -m pip install -r tool/requirements-browser.txt
    .\.venv-browser\Scripts\python.exe tool/browser_smoke.py

The test uses installed Chrome; BROWSER_CHANNEL can select another Playwright-supported installed browser. APPLIANCE_UI_ORIGIN and APPLIANCE_API_ORIGIN override the default loopback ports. The token comes from API_TOKEN or the root .env and is never printed.

This integration check changes the simulated device's absolute power setting. It blocks API requests in the browser, queues a command, reloads the page, checks that SQLite retained the same ID, restores networking and verifies the backend receipt and simulator confirmation. It writes credential-free screenshots and a JSON result under the root artifacts directory.

Live event bursts are coalesced into at most one requested repair per second; five-second polling remains the recovery path if events are missed.
