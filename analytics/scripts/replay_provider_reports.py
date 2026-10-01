"""Re-execute saved candidates after guard changes, without contacting any model."""
import hashlib
import json
from pathlib import Path

from appliance_analytics.assistant import UnsafeSQL, equivalent_rows, query
from appliance_analytics.ingest import connect

root = Path(__file__).resolve().parents[1]
fixture_path = root / "evals" / "provider_cases.json"
cases = {case["question"]: case for case in json.loads(fixture_path.read_text())}
con = connect(root / "data" / "reference.duckdb")
reports = []
try:
    for name in ("ollama-eval.json", "ollama-qwen35-eval.json"):
        path = root / "artifacts" / name
        original = json.loads(path.read_text())
        results = []
        for saved in original["results"]:
            case = cases[saved["question"]]
            expected = con.execute(case["expected_sql"]).fetchall() if case.get("expected_sql") else None
            if saved.get("sql"):
                try:
                    answer = query(con, saved["sql"])
                except UnsafeSQL:
                    answer = {"status": "rejected"}
            else:
                answer = {"status": saved["planner_status"]}
            if answer["status"] == "error":
                passed, outcome = False, "provider_or_execution_error"
            elif expected is not None:
                passed = answer["status"] == "answered" and equivalent_rows(answer["rows"], expected, case.get("ordered", False))
                outcome = "correct_answer" if passed else "wrong_answer" if answer["status"] == "answered" else answer["status"]
            else:
                passed = answer["status"] in {"abstained", "rejected"}
                outcome = "correct_refusal" if passed else "unsupported_answer"
            unchanged = passed == saved["passed"] and outcome == saved["outcome"]
            results.append({"question": case["question"], "passed": passed, "outcome": outcome, "original_outcome": saved["outcome"], "outcome_unchanged": unchanged})
        reports.append({"model": original["model"], "original_report": name,
                        "original_report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "cases": len(results), "passed": sum(r["passed"] for r in results),
                        "all_outcomes_unchanged": all(r["outcome_unchanged"] for r in results), "results": results})
finally:
    con.close()
result = {"scope": "saved SQL replay only; no new model generation; current seasonal-naive reference table",
          "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(), "reports": reports}
output = root / "artifacts" / "provider-guard-replay.json"
output.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"reports": [{k:v for k,v in report.items() if k != "results"} for report in reports]}, indent=2))
if not all(report["all_outcomes_unchanged"] for report in reports):
    raise SystemExit(1)
