"""Correctness checks for standalone dashboard input and embedding."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_dashboard import build_payload, render


class DashboardInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="energy-dashboard-unit-")
        self.root = Path(self.temp.name)
        self.daily = {
            "device_id": "fan-1", "source_kind": "simulated", "day": "2025-01-01",
            "energy_wh": "240", "unallocated_energy_wh": "0",
            "coverage_seconds": "86400", "coverage_ratio": "1", "reading_count": "24",
            "mean_power_w": "10", "peak_power_w": "12", "gap_count": "0",
            "reset_count": "0", "invalid_interval_count": "0",
        }
        self.forecast = {
            "device_id": "fan-1", "source_kind": "simulated",
            "forecast_origin": "2025-01-01", "target_date": "2025-01-02",
            "model": "seasonal_naive", "prediction_wh": "240", "lower_wh": "200",
            "upper_wh": "300", "interval_nominal": ".9", "horizon_days": "1",
            "interval_status": "calibrated_one_day",
        }
        self.write("gold_device_daily.csv", [self.daily])
        self.write("forecast_daily.csv", [self.forecast])

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, rows):
        with (self.root / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)

    def test_manifest_checksum_and_row_grain_are_enforced(self):
        manifest = {"tables": {"gold_device_daily": {"sha256": hashlib.sha256(
            (self.root / "gold_device_daily.csv").read_bytes()).hexdigest()}}}
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertTrue(build_payload(self.root)["provenance"]["gold_device_daily.csv"]["manifest_verified"])
        self.write("gold_device_daily.csv", [self.daily, self.daily])
        with self.assertRaisesRegex(ValueError, "duplicate analytical grain"):
            build_payload(self.root)
        changed = dict(self.daily, energy_wh="250")
        self.write("gold_device_daily.csv", [changed])
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            build_payload(self.root)

    def test_nonfinite_energy_and_unknown_sources_fail(self):
        self.write("gold_device_daily.csv", [dict(self.daily, energy_wh="nan")])
        with self.assertRaisesRegex(ValueError, "non-finite"):
            build_payload(self.root)
        self.write("gold_device_daily.csv", [dict(self.daily, source_kind="combined")])
        with self.assertRaisesRegex(ValueError, "unknown source_kind"):
            build_payload(self.root)

    def test_invalid_forecast_interval_fails(self):
        self.write("forecast_daily.csv", [dict(self.forecast, lower_wh="400")])
        with self.assertRaisesRegex(ValueError, "invalid forecast interval"):
            build_payload(self.root)

    def test_embedded_values_cannot_close_the_data_script(self):
        self.write("gold_device_daily.csv", [dict(
            self.daily, device_id="</script><script>alert('x')</script>")])
        html = render(build_payload(self.root))
        self.assertNotIn("</script><script>alert", html)
        self.assertIn("\\u003c/script>", html)


if __name__ == "__main__":
    unittest.main()
