# Local energy decision dashboard

The standalone report at ../artifacts/energy-dashboard.html is generated from the exported analytical tables. It complements the Power BI project with a portable browser view that can be inspected without a Power BI account or native application.

## Rebuild and open

From the repository root:

    python scripts/build_dashboard.py --data analytics/artifacts/powerbi --output artifacts/energy-dashboard.html

The generator uses only the Python standard library. Open the resulting HTML file directly in a browser. It embeds its data, CSS, JavaScript and SVG charts; it fetches no external rendering dependency. An optional --metrics path selects another forecast-summary.json. By default metrics and forecast-policy.json are read from the sibling forecast directory.

The input CSV checksums are compared with manifest.json when supplied. Duplicate analytical grains, non-finite values, invalid source kinds and impossible forecast intervals fail the build. A declared published model must match the forecast export.

## Reading the report

Choose exactly one source cohort. The initial cohort is simulated when available. Selecting measured or another empty cohort displays no observations, without substituting synthetic data.

The energy scope can be one device or all devices within the selected cohort. Recorded energy is expressed in kWh; the source CSV uses Wh. Unallocated energy is shown separately and excluded. Coverage uses the exported rows as its denominator, not a presumed complete fleet inventory. Partial coverage, absent dates and quality exceptions are visible; missing intervals are not zero-filled.

Forecasts are per device. Marginal intervals are never summed into a supposed fleet interval. The published seasonal-naive model is labelled baseline reference; ridge comparison metrics remain visible. The report labels the nominal 90% interval and the provisional later horizons, while distinguishing one-day holdout coverage from guaranteed future coverage.

The supplied dataset is generated appliance history. The view makes no measured savings, physical hardware or production-operation claim.

## Validation

On 2026-10-01:

- Four standard-library input/embedding tests passed using python scripts/test_dashboard.py.
- The actual report passed a Chrome 154.0.8037.59 check of chart labels, baseline policy, CSV-to-display energy totals and zero page errors.
- Selecting an empty measured cohort showed no fallback data.
- A planted nonempty measured cohort remained separate from the simulated cohort; simulated total remained unchanged.
- The displayed simulated recorded energy was 221.278 kWh over 142 exported device-days, including two partial-coverage rows.
- JSON validation result: ../artifacts/energy-dashboard-validation.json.
- [Inspected dashboard screenshot](images/energy-dashboard.png).

Run the browser check with the optional Playwright environment installed for mobile verification:

    mobile/.venv-browser/Scripts/python.exe scripts/test_dashboard_browser.py

The CSVs and forecast reports remain the source of analytical facts; this renderer does not alter analytics code, data or model artifacts.
