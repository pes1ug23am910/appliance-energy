"""Verify connector selection, secret exclusion and independent cohort filters."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("powerbi_source", SCRIPTS / "powerbi_source.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


def config(tmp_path, **updates):
    settings = {"host": "example.cloud.databricks.com", "http_path": "/sql/1.0/warehouses/123456"}
    settings.update(updates)
    path = tmp_path / "connection.json"
    path.write_text(json.dumps(settings))
    return path


@pytest.mark.parametrize("cloud,connector", [("aws", "DatabricksMultiCloud"), ("azure", "Databricks")])
def test_correct_connector_and_every_table_is_cohort_filtered(tmp_path, cloud, connector):
    parameters = source.connection_parameters(config(tmp_path, cloud=cloud))
    for table in ("gold_device_daily", "forecast_daily"):
        query = "\n".join(source.native_source(table, ["source_kind"], ['{"source_kind", type text}'], parameters))
        assert f"{connector}.Catalogs(" in query
        assert 'Implementation="2.0"' in query
        assert "each [source_kind] = SourceKind" in query
        assert "File.Contents" not in query
        assert f'Name="{table}"' in query


@pytest.mark.parametrize("updates", [{"token": "do-not-store"}, {"host": "https://example.com"}, {"host": "token@example.com"}, {"http_path": "/cluster/123"}, {"schema": 'x"; code'}, {"cloud": "unknown"}])
def test_invalid_connections_and_credentials_rejected(tmp_path, updates):
    with pytest.raises(ValueError):
        source.connection_parameters(config(tmp_path, **updates))


def test_unapproved_table_rejected(tmp_path):
    with pytest.raises(ValueError):
        source.native_source("silver_telemetry", [], [], source.connection_parameters(config(tmp_path)))


def test_m_literal_does_not_interpret_path_quotes_or_escape_sequences():
    assert source.m_text('path/#(lf)/"quoted"') == '"path/#(#)(lf)/""quoted"""'


def test_csv_and_databricks_build_same_report_schema(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "gold_device_daily.csv").write_text("device_id,source_kind,day,energy_wh,unallocated_energy_wh,coverage_ratio,gap_count,reset_count,invalid_interval_count\n")
    (data / "forecast_daily.csv").write_text("device_id,source_kind,target_date,model,prediction_wh,lower_wh,upper_wh,interval_nominal,interval_status\n")
    models = []
    for mode in ("csv", "databricks"):
        output = tmp_path / mode
        command = [sys.executable, str(SCRIPTS / "build_powerbi.py"), "--data", str(data), "--output", str(output)]
        if mode == "databricks":
            command += ["--databricks-config", str(config(tmp_path))]
        result = subprocess.run(command, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        models.append(json.loads((output / "Energy.SemanticModel/model.bim").read_text())["model"])
    for index in range(2):
        assert models[0]["tables"][index]["columns"] == models[1]["tables"][index]["columns"]
    assert "DataFolder" not in {p["name"] for p in models[1]["expressions"]}
    assert len(models[1]["tables"][0]["measures"]) == 4


def test_missing_quality_columns_fail_before_creating_artifact(tmp_path):
    (tmp_path / "gold_device_daily.csv").write_text("device_id,energy_wh\n")
    result = subprocess.run([sys.executable, str(SCRIPTS / "build_powerbi.py"), "--data", str(tmp_path), "--output", str(tmp_path / "out")], text=True, capture_output=True)
    assert result.returncode != 0
    assert "coverage_ratio" in result.stderr
    assert not (tmp_path / "out/Energy.pbip").exists()
