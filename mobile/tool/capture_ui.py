from pathlib import Path
import os
import re
import sys
from playwright.sync_api import sync_playwright
from browser_smoke import TOKEN, ARTIFACTS, login

def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("BROWSER_CHANNEL", "chrome"), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        login(page)
        page.wait_for_timeout(1200)
        page.get_by_role("textbox", name="Search devices").fill("device-0001")
        page.wait_for_timeout(400)
        page.screenshot(path=str(ARTIFACTS / "mobile-fleet.png"), full_page=True)
        page.get_by_role("button", name=re.compile(r"device-0001")).first.click(force=True)
        page.get_by_role("button", name="Save and send command").wait_for(timeout=10000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(ARTIFACTS / "mobile-device.png"), full_page=True)
        page.set_viewport_size({"width": 430, "height": 932})
        page.wait_for_timeout(500)
        page.screenshot(path=str(ARTIFACTS / "mobile-narrow-device.png"), full_page=True)
        browser.close()

if __name__ == "__main__":
    try:
        capture()
    except Exception as error:
        print(type(error).__name__ + ": " + str(error).replace(TOKEN, "[REDACTED]"))
        sys.exit(1)
