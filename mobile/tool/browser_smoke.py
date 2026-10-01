from pathlib import Path
import json
import os
import re
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TOKEN = os.environ.get("API_TOKEN") or next(line.split("=", 1)[1].strip().strip('"').strip("'")
             for line in (ROOT / ".env").read_text().splitlines() if line.startswith("API_TOKEN="))
API = os.environ.get("APPLIANCE_API_ORIGIN", "http://127.0.0.1:18080")
UI = os.environ.get("APPLIANCE_UI_ORIGIN", "http://127.0.0.1:8090")
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


def get(path):
    with urlopen(Request(API + path, headers={"Authorization": "Bearer " + TOKEN}), timeout=10) as response:
        return json.load(response)


def login(page):
    page.goto(UI)
    page.get_by_role("textbox").nth(0).wait_for(timeout=20000)
    page.get_by_role("textbox").nth(0).fill(API)
    page.get_by_role("textbox").nth(1).fill(TOKEN)
    page.get_by_role("button", name="Open fleet").click(force=True)
    try:
        page.get_by_role("textbox", name="Search devices").wait_for(timeout=20000)
    except Exception:
        page.screenshot(path=str(ARTIFACTS / "mobile-smoke-failure.png"), full_page=True)
        print("LOGIN_LABELS", page.locator("[aria-label]").evaluate_all(
            "(elements) => elements.map(e => e.getAttribute('aria-label')).join(' | ')").replace(TOKEN, "[REDACTED]"))
        raise
    print("LOGIN_OK", flush=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel=os.environ.get("BROWSER_CHANNEL", "chrome"), headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        errors = []
        outgoing = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: outgoing.append(request.url))
        login(page)
        page.get_by_role("textbox", name="Search devices").fill("device-0001")
        device = page.get_by_role("button", name=re.compile(r"device-0001"))
        device.first.click(force=True)
        print("DETAIL_OPEN", flush=True)
        page.get_by_role("button", name="Save and send command").wait_for(timeout=10000)
        page.screenshot(path=str(ARTIFACTS / "mobile-device.png"), full_page=True)
        context.route("**/api/**", lambda route: route.abort())
        offline = page.get_by_role("button", name="Queue command locally")
        offline.wait_for(timeout=15000)
        switches = page.get_by_role("switch")
        switches.first.click(force=True)
        offline.click(force=True)
        page.wait_for_timeout(1000)
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(700)
        content = page.locator("body").inner_text()
        labels = page.locator("[aria-label]").evaluate_all(
            "(elements) => elements.map(e => e.getAttribute('aria-label')).join('\\n')")
        identities = re.findall(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", content + labels + page.locator("input, textarea").evaluate_all("(elements) => elements.map(e => e.value).join(' ')"))
        page.screenshot(path=str(ARTIFACTS / "mobile-offline-queue.png"), full_page=True)
        if not identities:
            print("QUEUE_LABELS", (content + labels + page.locator("input, textarea").evaluate_all("(elements) => elements.map(e => e.value).join(' ')")).replace(TOKEN, "[REDACTED]")[:6000])
        assert identities, "Queued command ID should be visible"
        command_id = identities[-1]
        print("QUEUED_VISIBLE", flush=True)
        page.screenshot(path=str(ARTIFACTS / "mobile-offline-queue.png"), full_page=True)
        login(page)
        page.get_by_role("button", name="Commands", exact=True).click(force=True)
        page.wait_for_timeout(700)
        labels = page.locator("[aria-label]").evaluate_all(
            "(elements) => elements.map(e => e.getAttribute('aria-label')).join('\\n')")
        assert command_id in page.locator("body").inner_text() + labels + page.locator("input, textarea").evaluate_all("(elements) => elements.map(e => e.value).join(' ')"), "Queue must survive browser reload"
        page.screenshot(path=str(ARTIFACTS / "mobile-restored-queue.png"), full_page=True)
        print("RELOAD_PERSISTED", flush=True)
        context.unroute("**/api/**")
        page.get_by_role("button", name="Refresh snapshots").click(force=True)
        receipt = None
        for _ in range(35):
            try:
                receipt = get("/api/commands/" + command_id)
                if receipt["status"] == "confirmed":
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)
        assert receipt is not None, "Persisted command should reach backend after reconnect"
        assert receipt["command_id"] == command_id, "Reconnection must keep the original identity"
        page.get_by_role("button", name="Refresh snapshots").click(force=True)
        page.wait_for_timeout(700)
        page.screenshot(path=str(ARTIFACTS / ("mobile-confirmed-command.png" if receipt["status"] == "confirmed" else "mobile-awaiting-device.png")), full_page=True)
        assert not any(TOKEN in url for url in outgoing), "Token must never enter a request URL"
        assert not errors, "Unexpected browser page error"
        report = {
            "ui": UI, "api": API, "browser": browser.version,
            "sqlite_reload_persistence": True,
            "original_command_id_preserved": True,
            "command_id": command_id,
            "receipt_status": receipt["status"],
            "token_in_urls": False,
            "request_origins": sorted({urlsplit(url).netloc for url in outgoing}),
            "page_errors": len(errors),
            "observed_at_unix": time.time(),
        }
        (ARTIFACTS / "mobile-browser-smoke.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        browser.close()
        if receipt["status"] != "confirmed":
            raise RuntimeError("Command accepted but simulator confirmation still outstanding")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(type(error).__name__ + ": " + str(error).replace(TOKEN, "[REDACTED]"))
        sys.exit(1)
