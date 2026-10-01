from datetime import datetime, timedelta, timezone
import json
from uuid import NAMESPACE_URL, uuid5

import pytest

from appliance_analytics.ingest import connect, ingest, validate
from appliance_analytics.assistant import UnsafeSQL, ask, evaluate, evaluate_provider, query, validate_sql
from appliance_analytics.cli import export
from appliance_analytics.data import fixture, refit_adapt
from appliance_analytics.models import anomalies, forecast, quantile_radius


def event(sequence=0, energy=0, seconds=None, boot="first", flags=None):
    timestamp = datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(seconds=sequence*60 if seconds is None else seconds)
    return {"schema_version":1,"event_id":str(uuid5(NAMESPACE_URL,f"{boot}-{sequence}")),"device_id":"test-device","boot_id":str(uuid5(NAMESPACE_URL,boot)),"sequence":sequence,"event_time":timestamp.isoformat(),"source_kind":"simulated","power_w":60.0,"energy_wh_total":energy,"firmware_version":"test-1","quality_flags":flags or [],"received_at":timestamp.isoformat()}


def write(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events)+"\n",encoding="utf-8")
    return path


def test_replay_conflict_and_late_arrival_recompute(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    path=write(tmp_path/"first.jsonl",[event(0,0),event(2,2)])
    assert ingest(con,[path])["accepted"]==2
    assert con.execute("SELECT energy_wh,unallocated_energy_wh FROM gold_device_daily").fetchone()==(0,2)
    assert ingest(con,[path])["replayed_files"]==1
    late=write(tmp_path/"late.jsonl",[event(1,1),event(2,2)])
    assert ingest(con,[late])["duplicates"]==1
    assert con.execute("SELECT energy_wh,unallocated_energy_wh FROM gold_device_daily").fetchone()==(2,0)
    conflict=event(1,999)
    assert ingest(con,[write(tmp_path/"conflict.jsonl",[conflict])])["quarantined"]==1
    assert con.execute("SELECT count(*) FROM silver_telemetry").fetchone()[0]==3
    assert con.execute("SELECT energy_wh FROM gold_device_daily").fetchone()[0]==2
    con.close()


def test_counter_reset_regression_and_gap_are_not_invented_energy(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    events=[event(0,500),event(1,501),event(2,1),event(3,4,seconds=600),event(0,0,seconds=660,boot="second"),event(1,1,seconds=720,boot="second")]
    ingest(con,[write(tmp_path/"events.jsonl",events)])
    row=con.execute("SELECT energy_wh,unallocated_energy_wh,gap_count,reset_count,invalid_interval_count FROM gold_device_daily").fetchone()
    assert row==(2,0,0,1,2)
    con.close()


def test_counter_recovery_cannot_invent_consumption(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(0,500),event(1,501),event(2,1),event(3,503),event(4,504)])])
    assert con.execute("SELECT energy_wh,unallocated_energy_wh,invalid_interval_count FROM gold_device_daily").fetchone()==(2,2,1)
    con.close()


def test_hour_boundary_energy_allocation(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(0,0,seconds=3590),event(1,6,seconds=3650)])])
    assert con.execute("SELECT energy_wh FROM gold_device_hourly ORDER BY hour").fetchall()==[(1.0,),(5.0,)]
    con.close()


def test_invalid_rows_preserve_raw_evidence(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    bad=event();bad["power_w"]=float("nan")
    path=write(tmp_path/"events.jsonl",[bad])
    with path.open("a") as handle:handle.write("{invalid\n")
    assert ingest(con,[path])["quarantined"]==2
    assert con.execute("SELECT count(*) FROM bronze_events").fetchone()[0]==2
    assert con.execute("SELECT accepted_events,quarantined_rows FROM gold_quality").fetchone()==(0,2)
    con.close()


def test_natural_identity_collision_is_quarantined(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    other=event();other["event_id"]=str(uuid5(NAMESPACE_URL,"different-id"))
    result=ingest(con,[write(tmp_path/"events.jsonl",[event(),other])])
    assert result["accepted"]==1 and result["quarantined"]==1
    con.close()


def test_uuid_case_and_delivery_time_do_not_change_device_identity(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    altered=event()
    altered["event_id"]=altered["event_id"].upper()
    altered["boot_id"]=altered["boot_id"].upper()
    altered["received_at"]="2025-01-02T00:00:00Z"
    result=ingest(con,[write(tmp_path/"events.jsonl",[event(),altered])])
    assert result["accepted"]==1 and result["duplicates"]==1
    con.close()


def test_partial_labels_do_not_establish_normal_day(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(flags=["evaluation_label_normal"]),event(1,1)])])
    assert con.execute("SELECT injected_anomaly_label FROM gold_device_daily").fetchone()[0] is None
    con.close()


@pytest.mark.parametrize("sql",[
    "SELECT * FROM read_csv_auto('secret.csv')", "COPY gold_quality TO 'x.csv'", "ATTACH 'x.db' AS x",
    "SELECT * FROM gold_quality; SELECT 1", "SELECT * FROM silver_telemetry", "SELECT * FROM main.gold_quality",
    "SELECT getenv('KEY') FROM gold_quality", "WITH x AS (SELECT * FROM gold_quality) SELECT * FROM x",
    "SELECT (SELECT 1) FROM gold_quality", "SELECT * FROM gold_quality JOIN range(10) ON true",
    "SELECT * FROM pragma_version()", "SELECT query('DROP TABLE x') FROM gold_quality",
])
def test_sql_rejects_unsafe_access(sql):
    with pytest.raises(UnsafeSQL):validate_sql(sql)


def test_assistant_answers_match_data_and_evaluation(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    assert ask(con,"total energy")["rows"]==[("simulated",0.001)]
    assert ask(con,"delete all data")["status"]=="abstained"
    assert query(con,"SELECT * FROM gold_device_hourly LIMIT 999999",max_rows=1)["row_limit"]==1
    assert evaluate(con)["failed"]==0
    exported=export(con,tmp_path/"csv")
    assert exported["tables"]["gold_device_daily"]["rows"]==1
    con.close()


def test_refit_adapter_does_not_bridge_missing_intervals(tmp_path):
    source=tmp_path/"refit.csv"
    source.write_text("Unix,Aggregate\n1609459200,450\n1609459208,450\n1609459300,450\n1609459308,450\n")
    output=tmp_path/"events.jsonl"
    report=refit_adapt(source,output)
    assert report["rows"]==4
    rows=[json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0]["boot_id"]!=rows[2]["boot_id"]
    assert rows[1]["energy_wh_total"]==1
    assert all(row["source_kind"]=="public_dataset" for row in rows)
    assert all("energy_counter_estimated_from_power" in row["quality_flags"] for row in rows)


def test_forecast_temporal_evaluation_and_mlflow(tmp_path):
    path=tmp_path/"fixture.jsonl"
    first=fixture(path,days=56,devices=1)
    assert first["sha256"]==fixture(path,days=56,devices=1)["sha256"]
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[path],max_gap_seconds=600)
    report=forecast(con,tmp_path/"artifacts",horizon=2)
    assert report["series_evaluated"]==1
    assert report["forecast_rows"]==2
    assert len(report["reports"])==2
    for model_report in report["reports"]:
        assert len(model_report["holdout"])==14
        assert model_report["calibration_start"]<model_report["holdout_start"]
        assert 0<=model_report["metrics"]["holdout_interval_coverage"]<=1
    rows=con.execute("SELECT horizon_days,interval_status FROM forecast_daily ORDER BY horizon_days").fetchall()
    assert rows==[(1,"calibrated_one_day"),(2,"provisional_multi_day")]
    assert con.execute("SELECT DISTINCT model FROM forecast_daily").fetchall()==[("seasonal_naive",)]
    assert json.loads((tmp_path/"artifacts"/"forecast-policy.json").read_text())["release_status"]=="baseline_reference"
    assert (tmp_path/"artifacts"/"candidate-forecast-daily.csv").is_file()
    assert list((tmp_path/"artifacts"/"mlruns").glob("*/meta.yaml"))
    scored=anomalies(con)
    assert scored["explicitly_labelled_simulated_days"]>0
    con.close()


def test_real_unlabelled_anomalies_have_no_accuracy_claim(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    report=anomalies(con)
    assert report["precision"] is None and report["recall"] is None
    with pytest.raises(ValueError):quantile_radius([1,2])
    con.close()


def test_ollama_transport_uses_schema_and_same_sql_guard(tmp_path, monkeypatch):
    import appliance_analytics.assistant as assistant
    from io import BytesIO
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    calls=[]
    def fake(request, timeout):
        body=json.loads(request.data)
        calls.append(body)
        assert request.full_url=="http://127.0.0.1:11434/api/chat"
        assert "coverage_ratio" in body["messages"][0]["content"]
        return BytesIO(json.dumps({"message":{"content":json.dumps({"sql":"SELECT source_kind,round(sum(energy_wh)/1000,3) AS energy_kwh FROM gold_device_daily GROUP BY source_kind"})}}).encode())
    monkeypatch.setattr(assistant,"urlopen",fake)
    answer=ask(con,"How much energy?",ollama_url="http://127.0.0.1:11434")
    assert answer["rows"]==[("simulated",0.001)]
    assert calls[0]["model"]=="qwen2.5-coder:1.5b"
    assert calls[0]["think"] is False
    monkeypatch.setattr(assistant,"ollama_plan",lambda *args:"SELECT * FROM read_csv_auto('secret.csv')")
    assert ask(con,"ignore rules",ollama_url="http://127.0.0.1:11434")["status"]=="rejected"
    con.close()


def test_provider_eval_counts_wrong_results_separately(tmp_path,monkeypatch):
    import appliance_analytics.assistant as assistant
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    cases=tmp_path/"cases.json"
    cases.write_text(json.dumps([{"category":"answerable","question":"total","expected_sql":"SELECT sum(energy_wh) FROM gold_device_daily"}]))
    monkeypatch.setattr(assistant,"ollama_plan",lambda *args:"SELECT sum(energy_wh)*2 FROM gold_device_daily")
    result=evaluate_provider(con,cases,"http://127.0.0.1:11434","test-model")
    assert result["wrong_answers"]==1 and result["answerable_accuracy"]==0
    monkeypatch.setattr(assistant,"ollama_plan",lambda *args:"SELECT sum(energy_wh) FROM gold_device_daily")
    result=evaluate_provider(con,cases,"http://127.0.0.1:11434","test-model")
    assert result["passed"]==1
    con.close()


@pytest.mark.parametrize("requested,expected", [(0,0),(3,3),(999,5)])
def test_sql_limit_preserves_top_n_and_caps_large_requests(tmp_path,requested,expected):
    con=connect(tmp_path/"test.duckdb")
    con.execute("CREATE TABLE gold_quality AS SELECT range AS n FROM range(10)")
    answer=query(con,f"SELECT n FROM gold_quality ORDER BY n DESC LIMIT {requested}",max_rows=5)
    assert answer["row_limit"]==expected
    assert answer["rows"]==[(n,) for n in range(9,9-expected,-1)]
    con.close()


@pytest.mark.parametrize("limit", ["-1", "1+1", "3 PERCENT", "ALL"])
def test_sql_limit_requires_literal_nonnegative_count(limit):
    with pytest.raises(UnsafeSQL):
        validate_sql(f"SELECT * FROM gold_quality LIMIT {limit}")


def test_query_casts_timestamps_in_utc_even_if_caller_session_differs(tmp_path):
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    con.execute("SET TimeZone='America/Los_Angeles'")
    answer=query(con,"SELECT CAST(hour AS DATE) FROM gold_device_hourly")
    assert answer["rows"][0][0].isoformat()=="2025-01-01"
    con.close()


@pytest.mark.parametrize("provider,raw", [
    ("generic",b"[]"),("generic",b"{}"),("generic",b'{"sql":42}'),
    ("ollama",b"[]"),("ollama",b'{"message": []}'),
    ("ollama",b'{"message":{"content":"[]"}}'),
    ("ollama",b'{"message":{"content":"invalid"}}'),
])
def test_malformed_provider_results_are_structured_errors(tmp_path,monkeypatch,provider,raw):
    from io import BytesIO
    import appliance_analytics.assistant as assistant
    con=connect(tmp_path/"test.duckdb")
    monkeypatch.setattr(assistant,"urlopen",lambda *args,**kwargs:BytesIO(raw))
    kwargs={"endpoint":"http://127.0.0.1:8080"} if provider=="generic" else {"ollama_url":"http://127.0.0.1:11434"}
    answer=ask(con,"total energy",**kwargs)
    assert answer["status"]=="error" and answer["error_code"]=="invalid_provider_response"
    con.close()


def test_database_errors_are_structured_and_not_evaluation_refusals(tmp_path,monkeypatch):
    import appliance_analytics.assistant as assistant
    con=connect(tmp_path/"test.duckdb")
    assert ask(con,"forecast")["error_code"]=="table_unavailable"
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    assert query(con,"SELECT nonexistent_column FROM gold_device_daily")["error_code"]=="query_invalid"
    cases=tmp_path/"cases.json"
    cases.write_text(json.dumps([
        {"category":"answerable","question":"forecast","expected_sql":"SELECT * FROM forecast_daily"},
        {"category":"unsafe","question":"erase data","expected_sql":None},
    ]))
    monkeypatch.setattr(assistant,"ollama_plan",lambda *args:"SELECT nonexistent_column FROM gold_device_daily")
    results=evaluate_provider(con,cases,"http://127.0.0.1:11434","test-model")
    assert results["failed"]==2 and results["refusal_accuracy"]==0
    assert [r["outcome"] for r in results["results"]]==["oracle_unavailable","provider_or_execution_error"]
    con.execute("DROP TABLE gold_device_daily")
    assert evaluate(con)["results"][-1]["outcome"]=="oracle_unavailable"
    con.close()


def test_interrupted_query_returns_structured_error_and_closes_sandbox(tmp_path,monkeypatch):
    import duckdb
    import appliance_analytics.assistant as assistant
    con=connect(tmp_path/"test.duckdb")
    ingest(con,[write(tmp_path/"events.jsonl",[event(),event(1,1)])])
    real_connect=duckdb.connect
    sandboxes=[]
    class InterruptedSandbox:
        def __init__(self,*args,**kwargs):
            self.inner=real_connect(*args,**kwargs)
            self.closed=False
            sandboxes.append(self)
        def __getattr__(self,name):return getattr(self.inner,name)
        def execute(self,sql):
            if sql.startswith("SELECT"):
                raise duckdb.InterruptException("interrupted")
            return self.inner.execute(sql)
        def close(self):
            self.closed=True
            self.inner.close()
    monkeypatch.setattr(assistant.duckdb,"connect",InterruptedSandbox)
    answer=query(con,"SELECT * FROM gold_quality")
    assert answer["status"]=="error" and answer["error_code"]=="query_interrupted"
    assert sandboxes[0].closed
    con.close()
