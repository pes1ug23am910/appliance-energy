"""Expanding-origin forecasts with separate calibration and untouched holdout."""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd


def predict(history: np.ndarray, dates: pd.DatetimeIndex, target_date, model: str) -> float:
    if model == "seasonal_naive":
        target = pd.Timestamp(target_date) - pd.Timedelta(days=7)
        matches = np.flatnonzero(dates == target)
        if not len(matches):
            raise ValueError("seasonal history unavailable")
        return max(0.0, float(history[matches[-1]]))
    if model != "ridge_calendar":
        raise ValueError("unknown model")
    origin = dates[0]
    def features(index):
        index = pd.DatetimeIndex(index)
        age = (index - origin).days.to_numpy() / 30.0
        return np.column_stack([np.ones(len(index)), age] + [(index.dayofweek == day).astype(float) for day in range(1, 7)])
    x = features(dates)
    penalty = np.eye(x.shape[1]) * 0.1
    penalty[0, 0] = 0
    weights = np.linalg.solve(x.T @ x + penalty, x.T @ history)
    return max(0.0, float((features([target_date]) @ weights)[0]))


def quantile_radius(residuals: list[float], coverage: float = 0.9) -> float:
    rank = int(np.ceil((len(residuals) + 1) * coverage))
    if rank > len(residuals):
        raise ValueError("not enough calibration residuals for interval coverage")
    return float(np.sort(residuals)[rank - 1])


def forecast(con, artifact_dir: str | Path, horizon: int = 7, min_coverage: float = 0.8) -> dict:
    if not 1 <= horizon <= 7 or not 0 <= min_coverage <= 1:
        raise ValueError("horizon must be 1..7 and coverage 0..1")
    artifacts = Path(artifact_dir).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri((artifacts / "mlruns").as_uri())
    mlflow.set_experiment("appliance-energy-forecast")
    daily = con.execute("SELECT * FROM gold_device_daily ORDER BY device_id,source_kind,day").df()
    output, candidate_output, reports, skips = [], [], [], []
    for (device, kind), group in daily.groupby(["device_id", "source_kind"]):
        group = group[group["coverage_ratio"] >= min_coverage].copy()
        # Only the latest consecutive complete segment is eligible. Missing days stay missing.
        if group.empty:
            skips.append({"device_id": device, "source_kind": kind, "reason": "no sufficiently covered days"})
            continue
        day_gaps = group["day"].diff().dt.days.ne(1)
        group = group.loc[group.index[day_gaps][-1]:]
        if len(group) < 56:
            skips.append({"device_id": device, "source_kind": kind, "reason": "need 56 consecutive sufficiently covered days", "available_days": len(group)})
            continue
        y = group["energy_wh"].to_numpy(dtype=float)
        dates = pd.DatetimeIndex(group["day"])
        series_path = artifacts / f"{device}-{kind}-training-series.csv"
        group[["day", "energy_wh", "coverage_ratio"]].to_csv(series_path, index=False)
        cal_start, test_start = len(y) - 28, len(y) - 14
        candidates = {}
        for model in ("seasonal_naive", "ridge_calendar"):
            calibration = [abs(y[t] - predict(y[:t], dates[:t], dates[t], model)) for t in range(cal_start, test_start)]
            radius = quantile_radius(calibration)
            predictions = np.array([predict(y[:t], dates[:t], dates[t], model) for t in range(test_start, len(y))])
            actual = y[test_start:]
            lower, upper = np.maximum(0, predictions - radius), predictions + radius
            errors = np.abs(actual - predictions)
            scale = np.mean(np.abs(y[7:cal_start] - y[:cal_start-7]))
            metrics = {"calibration_mae_wh": float(np.mean(calibration)), "holdout_mae_wh": float(errors.mean()), "holdout_rmse_wh": float(np.sqrt(np.mean((actual-predictions)**2))), "holdout_interval_coverage": float(np.mean((actual>=lower)&(actual<=upper))), "holdout_mean_interval_width_wh": float(np.mean(upper-lower))}
            if scale > 0:
                metrics["holdout_mase"] = float(errors.mean() / scale)
            candidates[model] = {"metrics": metrics, "radius": radius}
            report = {"device_id": device, "source_kind": kind, "model": model, "interval_method": "90% target absolute-residual calibration; coverage measured, not guaranteed under drift", "calibration_start": str(dates[cal_start].date()), "holdout_start": str(dates[test_start].date()), "holdout_end": str(dates[-1].date()), "holdout_protocol": "one-day expanding origin, prior observed holdout values available at subsequent origins", "metrics": metrics, "holdout": [{"day": str(day.date()), "actual_wh": float(a), "prediction_wh": float(p), "lower_wh": float(lo), "upper_wh": float(hi)} for day,a,p,lo,hi in zip(dates[test_start:],actual,predictions,lower,upper)]}
            reports.append(report)
            report_path = artifacts / f"{device}-{kind}-{model}.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            with mlflow.start_run(run_name=f"{device}-{kind}-{model}"):
                mlflow.log_params({"device_id": device, "source_kind": kind, "model": model, "calibration_days": 14, "holdout_days": 14, "interval_nominal": 0.9, "min_coverage": min_coverage})
                mlflow.log_metrics(metrics)
                mlflow.log_artifact(str(report_path))
                mlflow.log_artifact(str(series_path))
                mlflow.log_dict({"algorithm": model, "ridge_penalty": 0.1 if model == "ridge_calendar" else None,
                                 "history_file": series_path.name, "history_end": str(dates[-1].date()),
                                 "training_inputs": ["day", "energy_wh"], "source_kind": kind,
                                 "selection": "calibration MAE; holdout excluded from selection"}, "model-specification.json")
        calibration_selected = min(candidates, key=lambda name: candidates[name]["metrics"]["calibration_mae_wh"])
        # Publish the named reference baseline. The calibration winner remains
        # separate pending independent measured-domain promotion evidence.
        selected = "seasonal_naive"
        extended_y, extended_dates = y.copy(), dates.copy()
        candidate_y, candidate_dates = y.copy(), dates.copy()
        for step in range(1, horizon + 1):
            target = dates[-1] + pd.Timedelta(days=step)
            value = predict(extended_y, extended_dates, target, selected)
            radius = candidates[selected]["radius"]
            # Multi-day intervals reuse one-day residuals and are explicitly provisional.
            status = "calibrated_one_day" if step == 1 else "provisional_multi_day"
            output.append((device, kind, dates[-1].date(), target.date(), selected, value, max(0, value-radius), value+radius, 0.9, step, status))
            candidate_value = predict(candidate_y, candidate_dates, target, calibration_selected)
            candidate_radius = candidates[calibration_selected]["radius"]
            candidate_output.append((device, kind, dates[-1].date(), target.date(), calibration_selected, candidate_value, max(0,candidate_value-candidate_radius), candidate_value+candidate_radius, 0.9, step, status, "unpromoted_research_candidate", calibration_selected))
            extended_y = np.append(extended_y, value)
            extended_dates = extended_dates.append(pd.DatetimeIndex([target]))
            candidate_y = np.append(candidate_y,candidate_value)
            candidate_dates = candidate_dates.append(pd.DatetimeIndex([target]))
    con.execute("""CREATE OR REPLACE TABLE forecast_daily (device_id VARCHAR, source_kind VARCHAR,
      forecast_origin DATE, target_date DATE, model VARCHAR, prediction_wh DOUBLE, lower_wh DOUBLE,
      upper_wh DOUBLE, interval_nominal DOUBLE, horizon_days INTEGER, interval_status VARCHAR)""")
    if output:
        con.executemany("INSERT INTO forecast_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", output)
    columns = ["device_id","source_kind","forecast_origin","target_date","model","prediction_wh","lower_wh","upper_wh","interval_nominal","horizon_days","interval_status","release_status","calibration_selected_model"]
    pd.DataFrame(candidate_output,columns=columns).to_csv(artifacts/"candidate-forecast-daily.csv",index=False)
    policy = {"table":"forecast_daily","published_model":"seasonal_naive","release_status":"baseline_reference",
              "candidate_artifact":"candidate-forecast-daily.csv","validation_scope":"research fixture; not validated for measured-device decisions"}
    (artifacts/"forecast-policy.json").write_text(json.dumps(policy,indent=2),encoding="utf-8")
    summary = {"series_evaluated": len(reports)//2, "forecast_rows": len(output), "skipped": skips, "reports": reports, "selection": "research candidate chosen by lowest calibration MAE; holdout not used for selection", "reference_policy": "forecast_daily retains seasonal-naive baseline; candidate-forecast-daily.csv is unpromoted research output; neither is validated for real-device decisions", "business_limit": "predictive evaluation does not measure intervention savings"}
    (artifacts / "forecast-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def anomalies(con, threshold: float = 4.0) -> dict:
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    data = con.execute("SELECT device_id,source_kind,day,energy_wh,coverage_ratio,injected_anomaly_label FROM gold_device_daily ORDER BY device_id,source_kind,day").df()
    rows = []
    for (device, kind), group in data.groupby(["device_id", "source_kind"]):
        observed = {}
        residual_history = []
        for r in group.itertuples():
            prior = observed.get(r.day - timedelta(days=7))
            label = None if pd.isna(r.injected_anomaly_label) else bool(r.injected_anomaly_label)
            if r.coverage_ratio >= 0.8 and prior is not None:
                residual = float(r.energy_wh - prior)
                if len(residual_history) >= 14:
                    history = np.array(residual_history[-28:])
                    center = float(np.median(history))
                    mad = float(np.median(np.abs(history-center)))
                    scale = max(1.0, 1.4826*mad)
                    score = abs(residual-center)/scale
                    rows.append((device, kind, r.day.date(), score, score > threshold, label, "seasonal_residual_mad", float(r.coverage_ratio)))
                residual_history.append(residual)
            if r.coverage_ratio >= 0.8:
                observed[r.day] = float(r.energy_wh)
    con.execute("""CREATE OR REPLACE TABLE anomaly_daily (device_id VARCHAR,source_kind VARCHAR,day DATE,
      score DOUBLE,is_alert BOOLEAN,injected_label BOOLEAN,method VARCHAR,coverage_ratio DOUBLE)""")
    if rows:
        con.executemany("INSERT INTO anomaly_daily VALUES (?,?,?,?,?,?,?,?)", rows)
    labelled = [r for r in rows if r[1] == "simulated" and r[5] is not None]
    tp = sum(r[4] and r[5] for r in labelled)
    fp = sum(r[4] and not r[5] for r in labelled)
    fn = sum(not r[4] and r[5] for r in labelled)
    return {"scored_days": len(rows), "explicitly_labelled_simulated_days": len(labelled), "true_positive": int(tp), "false_positive": int(fp), "false_negative": int(fn), "precision": tp/(tp+fp) if tp+fp else None, "recall": tp/(tp+fn) if tp+fn else None, "label_scope": "only explicit fixture/injection labels; real-data alerts are unverified candidates"}
