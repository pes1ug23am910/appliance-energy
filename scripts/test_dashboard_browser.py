"""Browser checks for the standalone dashboard using only local artifacts."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_dashboard", ROOT / "scripts/build_dashboard.py")
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


def main():
    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((ROOT / "artifacts/energy-dashboard.html").as_uri())
        page.wait_for_selector("#energy-chart circle")
        assert page.locator("#source").input_value() == "simulated"
        assert "Generated appliance data" in page.locator("#disclosure").inner_text()
        assert "kWh" in page.locator("#energy-chart").text_content()
        assert "provisional" in page.locator("#forecast-note").inner_text()
        assert "baseline reference" in page.locator("#forecast-caption").inner_text()
        assert page.locator("#forecast-model").inner_text() == "seasonal naive"
        expected = dashboard.build_payload(ROOT / "analytics/artifacts/powerbi")
        expected_energy = sum(row["energy_wh"] for row in expected["daily"] if row["source_kind"] == "simulated") / 1000
        actual_energy = float(page.locator("#energy-total").inner_text().replace(",", ""))
        assert abs(expected_energy - actual_energy) <= .00051
        result["simulated_energy_kwh"] = actual_energy
        result["source_filter_default"] = "simulated"
        result["csv_total_matches_display"] = True
        page.screenshot(path=str(ROOT / "docs/images/energy-dashboard.png"), full_page=True)
        page.locator("#source").select_option("measured")
        if not any(row["source_kind"] == "measured" for row in expected["daily"]):
            assert page.locator("#energy-total").inner_text() == "—"
            assert page.locator("#gap-total").inner_text() == "—"
            assert page.locator("#forecast-body").inner_text().startswith("No forecast")
            assert "No rows for this source cohort" in page.locator("#coverage-warning").inner_text()
        result["empty_cohort_no_synthetic_fallback"] = True
        # A planted second cohort proves nonempty filters do not combine provenance.
        fixture = json.loads(json.dumps(expected))
        measured = dict(fixture["daily"][0], device_id="measured-proof", source_kind="measured",
                        energy_wh=12345.0, unallocated_energy_wh=0.0)
        fixture["daily"].append(measured)
        with tempfile.TemporaryDirectory(prefix="appliance-dashboard-test-") as directory:
            path = Path(directory) / "mixed-cohorts.html"
            path.write_text(dashboard.render(fixture), encoding="utf-8")
            page.goto(path.as_uri())
            assert page.locator("#source").input_value() == "simulated"
            assert float(page.locator("#energy-total").inner_text().replace(",", "")) == actual_energy
            page.locator("#source").select_option("measured")
            assert float(page.locator("#energy-total").inner_text().replace(",", "")) == 12.345
            assert "measured-proof" in page.locator("#quality-body").inner_text()
            assert page.locator("#forecast-model").inner_text() == "unavailable"
        result["nonempty_cohorts_remain_separate"] = True
        assert not errors, errors
        result["page_errors"] = 0
        result["browser"] = browser.version
        browser.close()
    (ROOT / "artifacts/energy-dashboard-validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
