from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .assistant import UnsafeSQL, ask, evaluate, evaluate_provider, query
from .data import fetch_refit_sample, fixture, refit_adapt
from .ingest import connect, ingest
from .models import anomalies, forecast


def export(con, output: str | Path) -> dict:
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    available = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    manifest = {"format": "csv", "timezone": "UTC", "energy_unit": "Wh", "tables": {}}
    for table in sorted(available & {"gold_device_hourly", "gold_device_daily", "gold_quality", "forecast_daily", "anomaly_daily"}):
        frame = con.execute(f"SELECT * FROM {table}").df()
        path = directory / (table + ".csv")
        frame.to_csv(path, index=False)
        manifest["tables"][table] = {"rows": len(frame), "columns": list(frame.columns), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Appliance protocol analytics: explicit quality and source cohorts")
    p.add_argument("--db", default="data/analytics.duckdb")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("fixture"); s.add_argument("--output", required=True); s.add_argument("--days", type=int, default=70); s.add_argument("--devices", type=int, default=2)
    s = sub.add_parser("ingest"); s.add_argument("paths", nargs="+"); s.add_argument("--max-gap-seconds", type=float, default=120)
    s = sub.add_parser("forecast"); s.add_argument("--artifacts", default="artifacts/forecast"); s.add_argument("--horizon", type=int, default=7)
    s = sub.add_parser("anomalies"); s.add_argument("--threshold", type=float, default=4)
    s = sub.add_parser("ask"); s.add_argument("--question", required=True); s.add_argument("--planner-url"); s.add_argument("--ollama-url"); s.add_argument("--ollama-model", default="qwen2.5-coder:1.5b")
    s = sub.add_parser("sql"); s.add_argument("--query", required=True)
    s = sub.add_parser("evaluate"); s.add_argument("--fixtures"); s.add_argument("--output"); s.add_argument("--ollama-url"); s.add_argument("--ollama-model", default="qwen2.5-coder:1.5b")
    s = sub.add_parser("export"); s.add_argument("--output", required=True)
    s = sub.add_parser("refit-fetch"); s.add_argument("--output", required=True); s.add_argument("--rows", type=int, default=1000)
    s = sub.add_parser("refit-adapt"); s.add_argument("source"); s.add_argument("--output", required=True); s.add_argument("--power-column", default="Aggregate"); s.add_argument("--max-rows", type=int, default=10000); s.add_argument("--device-id", default="refit-house1")
    return p


def main() -> None:
    args = parser().parse_args()
    if args.command == "fixture":
        result = fixture(args.output, args.days, args.devices)
    elif args.command == "refit-fetch":
        result = fetch_refit_sample(args.output, args.rows)
    elif args.command == "refit-adapt":
        result = refit_adapt(args.source, args.output, args.power_column, args.max_rows, args.device_id)
    else:
        con = connect(args.db)
        try:
            if args.command == "ingest": result = ingest(con, args.paths, args.max_gap_seconds)
            elif args.command == "forecast": result = forecast(con, args.artifacts, args.horizon)
            elif args.command == "anomalies": result = anomalies(con, args.threshold)
            elif args.command == "ask": result = ask(con, args.question, args.planner_url,args.ollama_url,args.ollama_model)
            elif args.command == "sql":
                try:
                    result = query(con, args.query)
                except UnsafeSQL as exc:
                    result = {"status": "rejected", "reason": str(exc)}
            elif args.command == "evaluate":
                if args.ollama_url and not args.fixtures:
                    raise ValueError("provider evaluation requires --fixtures evals/provider_cases.json")
                result = evaluate_provider(con,args.fixtures,args.ollama_url,args.ollama_model) if args.ollama_url else evaluate(con, args.fixtures)
                if args.output:
                    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            elif args.command == "export": result = export(con, args.output)
            else: raise ValueError("unknown command")
        finally:
            con.close()
    print(json.dumps(result, indent=2, default=str, allow_nan=False))
    if args.command == "evaluate" and result["failed"]:
        raise SystemExit(1)
    if args.command in {"ask", "sql"} and result["status"] in {"error", "rejected"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
