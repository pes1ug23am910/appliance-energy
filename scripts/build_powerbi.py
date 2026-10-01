"""Generate an editable Power BI project from exported gold CSVs.

Only public PBIR schemas and ordinary Tabular model metadata are used. The
output is a local project; publishing to the Power BI service is separate.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/"


def write(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def expression(table, column, measure=False):
    return {"Measure" if measure else "Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def projection(table, column, measure=False):
    return {"field": expression(table, column, measure), "queryRef": f"{table}.{column}", "nativeQueryRef": column}


def visual(folder, name, kind, roles, position, title):
    query = {role: {"projections": fields} for role, fields in roles.items()}
    write(folder / "visuals" / name / "visual.json", {
        "$schema": SCHEMA + "report/definition/visualContainer/2.4.0/schema.json",
        "name": name, "position": dict(zip(("x", "y", "width", "height", "z"), position)),
        "visual": {"visualType": kind, "query": {"queryState": query},
                   "visualContainerObjects": {"title": [{"properties": {
                       "show": {"expr": {"Literal": {"Value": "true"}}},
                       "text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}
                   }}]}}})


def table_definition(name, filename, headers, numeric, dates):
    columns = []
    changes = []
    for header in headers:
        dtype = "dateTime" if header in dates else "double" if header in numeric else "string"
        columns.append({"name": header, "dataType": dtype, "sourceColumn": header,
                        "summarizeBy": "sum" if header in numeric else "none"})
        mtype = "type datetime" if header in dates else "type number" if header in numeric else "type text"
        changes.append('{"' + header + '", ' + mtype + '}')
    source = ["let", f'    Source = Csv.Document(File.Contents(DataFolder & "/{filename}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
              '    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
              '    Typed = Table.TransformColumnTypes(Headers, {' + ', '.join(changes) + '}, "en-US"),',
              '    Cohort = Table.SelectRows(Typed, each [source_kind] = SourceKind)', "in", "    Cohort"]
    return {"name": name, "columns": columns,
            "partitions": [{"name": name, "mode": "import", "source": {"type": "m", "expression": source}}]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/powerbi"))
    parser.add_argument("--source-kind", choices=["simulated", "measured", "estimated", "public_dataset"], default="simulated")
    args = parser.parse_args()
    data = args.data.resolve()
    output = args.output.resolve()
    required = {"Energy": "gold_device_daily.csv", "Forecast": "forecast_daily.csv"}
    headers = {}
    for name, filename in required.items():
        with (data / filename).open(encoding="utf-8-sig") as file:
            headers[name] = next(csv.reader(file))
    numeric = {"energy_wh", "unallocated_energy_wh", "coverage_seconds", "coverage_ratio", "reading_count", "mean_power_w", "peak_power_w", "gap_count", "reset_count", "invalid_interval_count", "prediction_wh", "lower_wh", "upper_wh", "interval_nominal", "horizon_days"}
    dates = {"day", "forecast_origin", "target_date"}
    tables = [table_definition(name, filename, headers[name], numeric, dates) for name, filename in required.items()]
    tables[0]["measures"] = [
        {"name": "Observed energy kWh", "expression": "DIVIDE(SUM(Energy[energy_wh]), 1000)", "formatString": "0.000"},
        {"name": "Unallocated energy kWh", "expression": "DIVIDE(SUM(Energy[unallocated_energy_wh]), 1000)", "formatString": "0.000"},
        {"name": "Mean coverage", "expression": "AVERAGE(Energy[coverage_ratio])", "formatString": "0.0%"},
        {"name": "Device count", "expression": "DISTINCTCOUNT(Energy[device_id])", "formatString": "0"},
    ]
    model = output / "Energy.SemanticModel"
    write(model / "definition.pbism", {"$schema": SCHEMA + "semanticModel/definitionProperties/1.0.0/schema.json", "version": "1.0", "settings": {}})
    write(model / "model.bim", {"name": "ApplianceEnergy", "compatibilityLevel": 1567,
        "model": {"culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3",
                  "expressions": [
                      {"name": "DataFolder", "kind": "m", "expression": json.dumps(data.as_posix()) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'},
                      {"name": "SourceKind", "kind": "m", "expression": json.dumps(args.source_kind) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}],
                  "tables": tables}})
    report = output / "Energy.Report"
    write(report / "definition.pbir", {"$schema": SCHEMA + "report/definitionProperties/2.0.0/schema.json", "version": "4.0", "datasetReference": {"byPath": {"path": "../Energy.SemanticModel"}}})
    definition = report / "definition"
    write(definition / "version.json", {"$schema": SCHEMA + "report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write(definition / "report.json", {"$schema": SCHEMA + "report/definition/report/3.1.0/schema.json", "themeCollection": {}})
    pages = [("overview", "Energy overview"), ("quality", "Coverage and missing data"), ("forecast", "Forecast and uncertainty")]
    write(definition / "pages/pages.json", {"$schema": SCHEMA + "report/definition/pagesMetadata/1.0.0/schema.json", "pageOrder": [p[0] for p in pages], "activePageName": "overview"})
    for page_id, title in pages:
        write(definition / "pages" / page_id / "page.json", {"$schema": SCHEMA + "report/definition/page/2.0.0/schema.json", "name": page_id, "displayName": title, "displayOption": "FitToPage", "width": 1280, "height": 720})
    overview = definition / "pages/overview"
    for index, metric in enumerate(["Observed energy kWh", "Mean coverage", "Device count"]):
        visual(overview, f"metric{index}", "card", {"Values": [projection("Energy", metric, True)]}, (24+index*410, 24, 390, 130, index), metric)
    visual(overview, "energyByDay", "lineChart", {"Category": [projection("Energy", "day")], "Y": [projection("Energy", "Observed energy kWh", True)], "Series": [projection("Energy", "source_kind")]}, (24, 180, 790, 490, 4), "Observed energy by day and source")
    visual(overview, "devices", "tableEx", {"Values": [projection("Energy", "device_id"), projection("Energy", "source_kind"), projection("Energy", "Observed energy kWh", True)]}, (840, 180, 410, 490, 5), "Device investigation")
    quality = definition / "pages/quality"
    visual(quality, "qualityTable", "tableEx", {"Values": [projection("Energy", column) for column in ["device_id", "source_kind", "day", "coverage_ratio", "gap_count", "reset_count", "invalid_interval_count", "unallocated_energy_wh"]]}, (24, 24, 1230, 650, 0), "Gaps and unallocated energy remain visible")
    forecast = definition / "pages/forecast"
    visual(forecast, "forecastTable", "tableEx", {"Values": [projection("Forecast", column) for column in ["device_id", "source_kind", "target_date", "model", "prediction_wh", "lower_wh", "upper_wh", "interval_nominal", "interval_status"] if column in headers["Forecast"]]}, (24, 24, 1230, 650, 0), "Forecast values and interval status in Wh")
    write(output / "Energy.pbip", {"version": "1.0", "artifacts": [{"report": {"path": "Energy.Report"}}], "settings": {"enableAutoRecovery": True}})
    print(json.dumps({"project": str(output / "Energy.pbip"), "pages": len(pages), "tables": len(tables)}))


if __name__ == "__main__":
    main()
