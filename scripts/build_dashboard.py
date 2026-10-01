"""Build a standalone, source-separated energy report from exported CSVs."""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SOURCE_KINDS = {"simulated", "measured", "estimated", "public_dataset"}
DAILY_NUMBERS = ("energy_wh", "unallocated_energy_wh", "coverage_seconds",
                 "coverage_ratio", "reading_count", "mean_power_w", "peak_power_w",
                 "gap_count", "reset_count", "invalid_interval_count")
FORECAST_NUMBERS = ("prediction_wh", "lower_wh", "upper_wh", "interval_nominal", "horizon_days")
def load_table(path: Path, numeric: tuple[str, ...], date_fields: tuple[str, ...]) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"device_id", "source_kind", *numeric, *date_fields}
        if path.name == "forecast_daily.csv":
            required |= {"model", "interval_status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
        rows = []
        keys = set()
        for ordinal, value in enumerate(reader, 2):
            if value["source_kind"] not in SOURCE_KINDS:
                raise ValueError(f"{path.name}:{ordinal}: unknown source_kind")
            if not value["device_id"]:
                raise ValueError(f"{path.name}:{ordinal}: empty device_id")
            for name in numeric:
                number = float(value[name])
                if not math.isfinite(number):
                    raise ValueError(f"{path.name}:{ordinal}: non-finite {name}")
                value[name] = number
            for name in date_fields:
                value[name] = date.fromisoformat(value[name].split("T")[0].split(" ")[0]).isoformat()
            if path.name == "gold_device_daily.csv":
                identity = (value["device_id"], value["source_kind"], value["day"])
                if value["energy_wh"] < 0 or not 0 <= value["coverage_ratio"] <= 1:
                    raise ValueError(f"{path.name}:{ordinal}: invalid energy or coverage")
                if not 0 <= value["coverage_seconds"] <= 86400:
                    raise ValueError(f"{path.name}:{ordinal}: invalid daily coverage duration")
            else:
                identity = (value["device_id"], value["source_kind"],
                            value["forecast_origin"], value["target_date"], value.get("model"))
                if not 0 <= value["lower_wh"] <= value["prediction_wh"] <= value["upper_wh"]:
                    raise ValueError(f"{path.name}:{ordinal}: invalid forecast interval")
                if not 0 < value["interval_nominal"] < 1:
                    raise ValueError(f"{path.name}:{ordinal}: invalid interval probability")
            if identity in keys:
                raise ValueError(f"{path.name}:{ordinal}: duplicate analytical grain")
            keys.add(identity)
            rows.append(value)
    return rows
def build_payload(data: Path, metrics_path: Path | None = None) -> dict:
    daily_path = data / "gold_device_daily.csv"
    forecast_path = data / "forecast_daily.csv"
    daily = load_table(daily_path, DAILY_NUMBERS, ("day",))
    forecasts = load_table(forecast_path, FORECAST_NUMBERS, ("forecast_origin", "target_date"))
    if not daily:
        raise ValueError("Daily export contains no records")
    provenance = {}
    manifest_path = data / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for path in (daily_path, forecast_path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = manifest.get("tables", {}).get(path.stem, {}).get("sha256")
        if expected and digest != expected:
            raise ValueError(f"{path.name}: checksum differs from manifest; rerun after export completes")
        provenance[path.name] = {"sha256": digest, "manifest_verified": bool(expected)}
    metrics_path = metrics_path or data.parent / "forecast" / "forecast-summary.json"
    summary = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    policy_path = metrics_path.parent / "forecast-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    if policy.get("published_model") and any(row.get("model") != policy["published_model"] for row in forecasts):
        raise ValueError("Forecast export does not match its declared published model")
    reports = [{key: record.get(key) for key in (
        "device_id", "source_kind", "model", "interval_method", "calibration_start",
        "holdout_start", "holdout_end", "holdout_protocol", "metrics")}
        for record in summary.get("reports", [])]
    return {"daily": daily, "forecasts": forecasts, "reports": reports,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provenance": provenance,
            "forecast_policy": policy}
def render(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace("&", "\\u0026")
    return HTML.replace("__DATA_JSON__", encoded)
HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Local appliance energy analytics with coverage and forecast uncertainty.">
<title>Appliance Energy · Decision dashboard</title>
<style>
:root{--ink:#173442;--muted:#5c707a;--teal:#087f8c;--blue:#2563aa;--amber:#a96108;--line:#dce5e9;--bg:#f3f6f8;--green:#137457}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{background:#102f3d;color:#fff;padding:30px max(24px,calc((100vw - 1260px)/2));border-bottom:4px solid #38b9b4}
header .eyebrow{font-size:12px;letter-spacing:.16em;color:#95ded7;font-weight:700}h1{font-size:32px;line-height:1.2;margin:8px 0}header p{margin:8px 0 0;color:#c6d9e0;max-width:900px}
main{max-width:1308px;padding:24px;margin:auto}h2{font-size:19px;line-height:1.3;margin:0 0 7px}h3{font-size:15px;margin:0 0 6px}p{margin:0 0 12px}.muted{color:var(--muted);font-size:13px}.panel{background:white;border:1px solid var(--line);border-radius:14px;padding:22px;box-shadow:0 2px 4px #15354404}
.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin-bottom:16px}label{display:block;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:6px}select{width:100%;padding:10px 12px;background:white;border:1px solid #b9cbd3;border-radius:7px;color:var(--ink);font:inherit}select:focus{outline:3px solid #a7dedb}
.notice{background:#e3f2ee;border:1px solid #bee0d2;padding:13px 16px;border-radius:10px;font-size:13px;margin-bottom:18px}.notice.warning{background:#fff1d9;border-color:#f1d5a0;color:#794500}.cohort{font-weight:750;text-transform:uppercase;letter-spacing:.04em;margin-right:8px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:16px 0 22px}.kpi{padding:18px 20px}.kpi .label{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}.kpi .value{font-size:31px;line-height:1.25;margin:7px 0;font-weight:650;font-variant-numeric:tabular-nums}.kpi .unit{font-size:14px;color:var(--muted);font-weight:500}.kpi .detail{color:var(--muted);font-size:12px}
.charts{display:grid;grid-template-columns:1.3fr 1fr;gap:18px;margin-bottom:18px}.chart{width:100%;height:auto;min-height:250px;display:block}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:5px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;background:var(--teal)}.dot.amber{background:#d18a1c}.dot.band{background:#d4e5f6}.sectionbar{display:flex;align-items:start;justify-content:space-between;gap:12px}.tag{border:1px solid #cbdde2;padding:3px 9px;border-radius:50px;font-size:11px;font-weight:650;color:var(--muted);white-space:nowrap}.tables{display:grid;grid-template-columns:1fr 1fr;gap:18px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;color:var(--muted);font-weight:650;background:#f7f9fa;white-space:nowrap}th,td{padding:10px;border-bottom:1px solid #e5ecef}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}.row-warning{background:#fff8eb}.row-current{background:#edf7f4}details{margin-top:16px}summary{cursor:pointer;font-weight:600;padding:5px 0}.empty{padding:50px 20px;text-align:center;color:var(--muted)}
#forecast-note{margin-top:12px;font-size:12px;border-left:3px solid #e2ad50;padding:8px 12px;background:#fff9ef}.footer{font-size:12px;color:var(--muted);padding:20px 0 5px}.footer code{font-size:11px;word-break:break-all}.toolbar-note{margin-top:7px;font-size:11px;color:var(--muted)}
@media(max-width:900px){.charts,.tables{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}.controls{grid-template-columns:1fr}.chart{min-height:220px}header{padding:24px}.sectionbar{flex-direction:column}}
@media(max-width:500px){main{padding:14px}.panel{padding:16px}.kpis{gap:10px}.kpi .value{font-size:25px}h1{font-size:27px}}
</style>
</head>
<body>
<header><div class="eyebrow">APPLIANCE ENERGY / DECISION LAB</div><h1>Energy, with the evidence attached.</h1><p>Review recorded consumption, find incomplete coverage, and compare a reference forecast with its uncertainty. All charts use UTC dates.</p></header>
<main>
<section class="panel controls" aria-label="Dashboard filters">
<div><label for="source">Source cohort</label><select id="source"></select><div class="toolbar-note">Exactly one source kind at a time.</div></div>
<div><label for="device">Energy scope</label><select id="device"></select><div class="toolbar-note">Fleet totals remain within the selected cohort.</div></div>
<div><label for="forecast-device">Forecast device</label><select id="forecast-device"></select><div class="toolbar-note">Intervals are shown per device, never summed.</div></div>
</section>
<div id="disclosure" class="notice"></div>
<section class="kpis" aria-label="Energy summary">
<div class="panel kpi"><div class="label">Recorded energy</div><div class="value"><span id="energy-total">—</span> <span class="unit">kWh</span></div><div id="energy-detail" class="detail"></div></div>
<div class="panel kpi"><div class="label">Coverage in exported days</div><div class="value"><span id="coverage-total">—</span> <span class="unit">%</span></div><div class="detail">Coverage seconds / (exported rows × 86,400)</div></div>
<div class="panel kpi"><div class="label">Gap events</div><div class="value" id="gap-total">—</div><div id="gap-detail" class="detail"></div></div>
<div class="panel kpi"><div class="label">Unallocated energy</div><div class="value"><span id="unallocated-total">—</span> <span class="unit">Wh</span></div><div class="detail">Excluded from recorded-energy totals</div></div>
</section>
<div id="coverage-warning" class="notice warning"></div>
<section class="charts">
<article class="panel"><div class="sectionbar"><div><h2>Daily recorded energy</h2><p id="energy-period" class="muted"></p></div><span id="energy-cohort" class="tag"></span></div>
<svg id="energy-chart" class="chart" viewBox="0 0 660 300" role="img" aria-label="Daily recorded energy in kilowatt-hours"></svg>
<div class="legend"><span><i class="dot"></i>Recorded intervals</span><span><i class="dot amber"></i>Partial coverage</span><span>Missing dates remain gaps</span></div></article>
<article class="panel"><div class="sectionbar"><div><h2>Next seven days</h2><p id="forecast-caption" class="muted"></p></div><span id="forecast-model" class="tag"></span></div>
<svg id="forecast-chart" class="chart" viewBox="0 0 520 300" role="img" aria-label="Device energy forecast and nominal prediction interval in kilowatt-hours"></svg>
<div class="legend"><span><i class="dot" style="background:#2563aa"></i>Reference forecast</span><span><i class="dot band"></i>Nominal interval</span></div><p id="forecast-note"></p></article>
</section>
<section class="tables">
<article class="panel"><h2>Coverage and quality exceptions</h2><p class="muted">Lowest coverage first. Missing device-days are not fabricated as zero-energy observations.</p><div class="scroll"><table><thead><tr><th>Device / UTC day</th><th class="num">Coverage</th><th class="num">Energy Wh</th><th class="num">Gaps / resets</th></tr></thead><tbody id="quality-body"></tbody></table></div><p id="quality-note" class="muted"></p></article>
<article class="panel"><h2>Baseline comparison</h2><p id="metrics-caption" class="muted">One-day expanding-origin holdout; per-device metrics.</p><div class="scroll"><table><thead><tr><th>Model</th><th class="num">MAE Wh</th><th class="num">Interval coverage</th><th class="num">Width Wh</th></tr></thead><tbody id="metrics-body"></tbody></table></div><p class="muted" style="margin-top:12px">Lower error alone is not an operational release decision. Coverage and interval width must be read together. Synthetic holdout results do not establish performance on measured appliances.</p></article>
</section>
<section class="panel" style="margin-top:18px"><h2>Forecast values and status</h2><div class="scroll"><table><thead><tr><th>UTC target</th><th>Horizon</th><th class="num">Prediction Wh</th><th class="num">Lower Wh</th><th class="num">Upper Wh</th><th>Interval status</th></tr></thead><tbody id="forecast-body"></tbody></table></div></section>
<details class="panel"><summary>Definitions and provenance</summary><p class="muted">Recorded energy sums valid covered intervals exported in gold_device_daily. It excludes unallocated intervals. Coverage here describes rows present in the export; it is not a complete fleet availability measure without an inventory and expected observation calendar. A missing row is not a zero. Forecast bands are marginal per-device intervals, not joint fleet risk bounds.</p><p id="provenance" class="muted"></p><p id="policy" class="muted"></p></details>
<div class="footer"><span id="generated"></span> · Standalone local report · No external scripts, fonts or chart services.</div>
</main>
<script type="application/json" id="dataset">__DATA_JSON__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("dataset").textContent);
const el=id=>document.getElementById(id);
const esc=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=(value,digits=2)=>Number(value).toLocaleString("en-US",{maximumFractionDigits:digits,minimumFractionDigits:digits});
const sum=(rows,key)=>rows.reduce((total,row)=>total+Number(row[key]||0),0);
const epoch=day=>Date.parse(day+"T00:00:00Z");
const dayText=day=>day.slice(5);
const sourceOptions=[...new Set(DATA.daily.map(r=>r.source_kind))].sort();
for(const kind of ["simulated","measured","estimated","public_dataset"]){
 const option=document.createElement("option");option.value=kind;
 option.textContent=kind.replaceAll("_"," ")+(sourceOptions.includes(kind)?"":" · no records");
 el("source").append(option);
}
el("source").value=sourceOptions.includes("simulated")?"simulated":sourceOptions[0];
const sourceRows=()=>DATA.daily.filter(row=>row.source_kind===el("source").value);
function options(){
 const ids=[...new Set(sourceRows().map(row=>row.device_id))].sort();
 el("device").innerHTML='<option value="__all__">All devices in this cohort</option>'+ids.map(id=>'<option value="'+esc(id)+'">'+esc(id)+'</option>').join("");
 const forecastIds=[...new Set(DATA.forecasts.filter(r=>r.source_kind===el("source").value).map(r=>r.device_id))].sort();
 el("forecast-device").innerHTML=forecastIds.length?forecastIds.map(id=>'<option value="'+esc(id)+'">'+esc(id)+'</option>').join(""):'<option value="">No forecast available</option>';
}
function axes(svg,width,days,max){
 const left=54,right=18,top=20,bottom=46,height=300,plotWidth=width-left-right,plotHeight=height-top-bottom;
 max=max>0?max*1.12:1;
 const minDay=days.length?epoch(days[0]):0,maxDay=days.length?epoch(days[days.length-1]):1;
 const x=day=>left+(epoch(day)-minDay)/Math.max(86400000,maxDay-minDay)*plotWidth;
 const y=value=>top+plotHeight-value/max*plotHeight;
 let parts=['<title>'+esc(svg.getAttribute("aria-label"))+'</title><text x="9" y="16" fill="#5c707a" font-size="11">kWh</text>'];
 for(let i=0;i<=4;i++){const value=max*i/4,yp=y(value);parts.push('<line x1="'+left+'" x2="'+(width-right)+'" y1="'+yp+'" y2="'+yp+'" stroke="#e1e9ed"/><text x="'+(left-9)+'" y="'+(yp+4)+'" text-anchor="end" fill="#5c707a" font-size="11">'+fmt(value,1)+'</text>');}
 const indices=[...new Set([0,Math.floor((days.length-1)/2),days.length-1])].filter(i=>i>=0);
 for(const index of indices){parts.push('<text x="'+x(days[index])+'" y="281" text-anchor="middle" fill="#5c707a" font-size="11">'+esc(dayText(days[index]))+'</text>');}
 parts.push('<text x="'+(width-right)+'" y="297" text-anchor="end" fill="#5c707a" font-size="10">UTC date</text>');
 return {x,y,parts};
}
function emptyChart(svg,message){
 svg.innerHTML='<text x="50%" y="48%" text-anchor="middle" fill="#5c707a" font-size="14">'+esc(message)+'</text>';
}
function energyChart(rows){
 const svg=el("energy-chart");if(!rows.length){emptyChart(svg,"No records in this cohort");return;}
 const grouped=new Map();
 for(const row of rows){if(!grouped.has(row.day))grouped.set(row.day,[]);grouped.get(row.day).push(row);}
 const days=[...grouped.keys()].sort(),expectedDevices=new Set(rows.map(r=>r.device_id)).size;
 const points=days.map(day=>({day,energy:sum(grouped.get(day),"energy_wh")/1000,
   partial:grouped.get(day).some(r=>r.coverage_ratio<.999)||grouped.get(day).length<expectedDevices}));
 const {x,y,parts}=axes(svg,660,days,Math.max(...points.map(p=>p.energy)));
 let previous=null;
 for(const point of points){
  if(previous&&epoch(point.day)-epoch(previous.day)===86400000&&!point.partial&&!previous.partial)
   parts.push('<line x1="'+x(previous.day)+'" y1="'+y(previous.energy)+'" x2="'+x(point.day)+'" y2="'+y(point.energy)+'" stroke="#087f8c" stroke-width="2.1"/>');
  parts.push('<circle cx="'+x(point.day)+'" cy="'+y(point.energy)+'" r="'+(point.partial?4:2.8)+'" fill="'+(point.partial?"#c78314":"#087f8c")+'"><title>'+esc(point.day)+' · '+fmt(point.energy,3)+' kWh'+(point.partial?' · partial coverage':'')+'</title></circle>');
  previous=point;
 }
 svg.innerHTML=parts.join("");
 el("energy-period").textContent=days[0]+" to "+days[days.length-1]+" · covered intervals only";
}
function forecastRows(){
 const filtered=DATA.forecasts.filter(r=>r.source_kind===el("source").value&&r.device_id===el("forecast-device").value);
 if(!filtered.length)return [];
 const latest=[...new Set(filtered.map(r=>r.forecast_origin))].sort().at(-1);
 const versions=filtered.filter(r=>r.forecast_origin===latest);
 const models=[...new Set(versions.map(r=>r.model))].sort();
 const model=models.includes("seasonal_naive")?"seasonal_naive":models[0];
 return versions.filter(r=>r.model===model).sort((a,b)=>a.target_date.localeCompare(b.target_date));
}
function forecastChart(rows){
 const svg=el("forecast-chart");
 if(!rows.length){
  emptyChart(svg,"No forecast for this source/device");
  el("forecast-caption").textContent="No eligible forecast records.";
  el("forecast-model").textContent="unavailable";el("forecast-note").textContent="No fallback from another source cohort is applied.";
  return;
 }
 const days=rows.map(r=>r.target_date),{x,y,parts}=axes(svg,520,days,Math.max(...rows.map(r=>r.upper_wh/1000)));
 const band=rows.map(r=>x(r.target_date)+","+y(r.upper_wh/1000)).concat([...rows].reverse().map(r=>x(r.target_date)+","+y(r.lower_wh/1000)));
 parts.push('<polygon points="'+band.join(" ")+'" fill="#d4e5f6" opacity=".9"/>');
 parts.push('<polyline points="'+rows.map(r=>x(r.target_date)+","+y(r.prediction_wh/1000)).join(" ")+'" fill="none" stroke="#2563aa" stroke-width="2.5" stroke-dasharray="6 3"/>');
 for(const row of rows)parts.push('<circle cx="'+x(row.target_date)+'" cy="'+y(row.prediction_wh/1000)+'" r="4" fill="#2563aa"><title>'+esc(row.target_date)+' · '+fmt(row.prediction_wh,1)+' Wh · '+esc(row.interval_status)+'</title></circle>');
 svg.innerHTML=parts.join("");
 el("forecast-caption").textContent=rows[0].device_id+" · origin "+rows[0].forecast_origin+" · "+(DATA.forecast_policy.release_status||"exported forecast").replaceAll("_"," ");
 el("forecast-model").textContent=rows[0].model.replaceAll("_"," ");
 const provisional=rows.filter(r=>r.interval_status.includes("provisional")).length;
 el("forecast-note").textContent=fmt(rows[0].interval_nominal*100,0)+"% nominal interval. "+
  (provisional?provisional+" later horizons are provisional: calibration and reported holdout coverage are one-day only.":"See per-row interval status and the calibration protocol.")+
  " Bands are not guaranteed future coverage.";
}
function updateForecast(){
 const rows=forecastRows();forecastChart(rows);
 el("forecast-body").innerHTML=rows.length?rows.map(row=>'<tr class="'+(row.interval_status.includes("provisional")?"row-warning":"")+'"><td>'+esc(row.target_date)+'</td><td>'+fmt(row.horizon_days,0)+' day</td><td class="num">'+fmt(row.prediction_wh,1)+'</td><td class="num">'+fmt(row.lower_wh,1)+'</td><td class="num">'+fmt(row.upper_wh,1)+'</td><td>'+esc(row.interval_status.replaceAll("_"," "))+'</td></tr>').join(""):'<tr><td colspan="6">No forecast records for the selected cohort.</td></tr>';
 const reports=DATA.reports.filter(r=>r.source_kind===el("source").value&&r.device_id===el("forecast-device").value);
 el("metrics-body").innerHTML=reports.length?reports.map(report=>'<tr class="'+(rows[0]&&report.model===rows[0].model?"row-current":"")+'"><td>'+esc(report.model.replaceAll("_"," "))+(rows[0]&&report.model===rows[0].model?' · exported':'')+'</td><td class="num">'+fmt(report.metrics.holdout_mae_wh,1)+'</td><td class="num">'+fmt(report.metrics.holdout_interval_coverage*100,1)+'%</td><td class="num">'+fmt(report.metrics.holdout_mean_interval_width_wh,1)+'</td></tr>').join(""):'<tr><td colspan="4">No evaluation metrics for this source/device.</td></tr>';
 el("metrics-caption").textContent=reports.length?reports[0].device_id+" · "+reports[0].holdout_start+" to "+reports[0].holdout_end+" · one-day expanding origin.":"No matched evaluation report.";
}
function update(){
 const source=el("source").value;
 const rows=sourceRows().filter(row=>el("device").value==="__all__"||row.device_id===el("device").value);
 const days=[...new Set(rows.map(row=>row.day))].sort();
 const devices=new Set(rows.map(row=>row.device_id));
 const partial=rows.filter(row=>row.coverage_ratio<.999);
 const span=days.length?Math.round((epoch(days.at(-1))-epoch(days[0]))/86400000)+1:0;
 const absentDates=span-days.length;
 const sourceNotes={
  simulated:"Generated appliance data. This demonstration has no measured savings or hardware-performance evidence.",
  measured:"Measured-source records only. Coverage and missing intervals still limit what can be concluded.",
  estimated:"Estimated-source records only. These values are distinct from measured and simulated telemetry.",
  public_dataset:"Public-dataset records only. Dataset provenance and availability assumptions remain part of interpretation."
 };
 el("disclosure").innerHTML='<span class="cohort">'+esc(source.replaceAll("_"," "))+'</span>'+sourceNotes[source];
 el("energy-cohort").textContent=source.replaceAll("_"," ");
 el("energy-total").textContent=rows.length?fmt(sum(rows,"energy_wh")/1000,3):"—";
 el("energy-detail").textContent=rows.length?devices.size+" device(s) · "+rows.length+" exported device-days":"No records for this selection";
 el("coverage-total").textContent=rows.length?fmt(sum(rows,"coverage_seconds")/(rows.length*86400)*100,2):"—";
 el("gap-total").textContent=rows.length?fmt(sum(rows,"gap_count"),0):"—";
 el("gap-detail").textContent=fmt(sum(rows,"invalid_interval_count"),0)+" invalid intervals · "+fmt(sum(rows,"reset_count"),0)+" resets";
 el("unallocated-total").textContent=rows.length?fmt(sum(rows,"unallocated_energy_wh"),3):"—";
 el("coverage-warning").textContent=rows.length?
  partial.length+" exported device-day(s) have partial coverage; "+absentDates+" calendar date(s) are absent from this selection. Missing device-day rows are outside the displayed coverage denominator. Totals are recorded energy, not reconstructed full-day consumption.":
  "No rows for this source cohort. The dashboard does not substitute simulated data or treat absence as zero.";
 el("coverage-warning").className="notice"+(!rows.length||partial.length||absentDates?" warning":"");
 if(!rows.length)el("energy-period").textContent="No observed date range.";
 energyChart(rows);
 const sorted=[...rows].sort((a,b)=>a.coverage_ratio-b.coverage_ratio||b.day.localeCompare(a.day)||a.device_id.localeCompare(b.device_id));
 const exceptions=sorted.filter(row=>row.coverage_ratio<.999||row.gap_count||row.reset_count||row.invalid_interval_count);
 const shown=(exceptions.length?exceptions:sorted).slice(0,8);
 el("quality-body").innerHTML=shown.length?shown.map(row=>'<tr class="'+(row.coverage_ratio<.999?"row-warning":"")+'"><td>'+esc(row.device_id)+'<br><span class="muted">'+esc(row.day)+'</span></td><td class="num">'+fmt(row.coverage_ratio*100,2)+'%</td><td class="num">'+fmt(row.energy_wh,2)+'</td><td class="num">'+fmt(row.gap_count,0)+' / '+fmt(row.reset_count,0)+'</td></tr>').join(""):'<tr><td colspan="4">No records.</td></tr>';
 el("quality-note").textContent=exceptions.length?"Showing "+shown.length+" of "+exceptions.length+" exception rows.":"No flagged exception rows; showing recent exported records.";
 updateForecast();
}
el("source").addEventListener("change",()=>{options();update();});
el("device").addEventListener("change",update);
el("forecast-device").addEventListener("change",updateForecast);
el("generated").textContent="Generated "+DATA.generated_at;
el("provenance").innerHTML=Object.entries(DATA.provenance).map(([name,value])=>esc(name)+" · "+(value.manifest_verified?"manifest verified":"no manifest checksum supplied")+"<br><code>"+esc(value.sha256)+"</code>").join("<br>");
el("policy").textContent="Forecast export metadata: "+JSON.stringify(DATA.forecast_policy);
options();update();
</script>
</body>
</html>"""
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "analytics" / "artifacts" / "powerbi")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "energy-dashboard.html")
    parser.add_argument("--metrics", type=Path, help="Forecast summary JSON; defaults beside the export directory")
    args = parser.parse_args()
    payload = build_payload(args.data, args.metrics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(payload), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "daily_rows": len(payload["daily"]),
                      "forecast_rows": len(payload["forecasts"]),
                      "source_kinds": sorted({r["source_kind"] for r in payload["daily"]})}, indent=2))
if __name__ == "__main__":
    main()
