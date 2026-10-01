# Databricks notebook source
# MAGIC %md
# MAGIC # Forecast evaluation and batch predictions
# MAGIC Requires NumPy, pandas and MLflow in the notebook environment. This adapter
# MAGIC has not been run against an account. Test data lineage and model artifacts there.

# COMMAND ----------
import re
import numpy as np
import pandas as pd
import mlflow

for name,default in (("catalog","workspace"),("schema","appliance_energy")):
    dbutils.widgets.text(name,default)
catalog,schema=(dbutils.widgets.get(name) for name in ("catalog","schema"))
assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",part) for part in (catalog,schema))
ns=f"{catalog}.{schema}"
spark.sql("SET TIME ZONE 'UTC'")
current_user=spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{current_user}/appliance-energy-forecast")
daily=spark.table(f"{ns}.gold_device_daily")
assert daily.count()<=100000,"Keep the student demo bounded before collecting daily aggregates"
data=daily.toPandas().sort_values(["device_id","source_kind","day"])
data["day"]=pd.to_datetime(data["day"])

def prediction(y,dates,target,model):
    if model=="seasonal_naive":
        matches=np.flatnonzero(dates==target-pd.Timedelta(days=7))
        return max(0.0,float(y[matches[-1]]))
    origin=dates[0]
    def features(index):
        index=pd.DatetimeIndex(index)
        return np.column_stack([np.ones(len(index)),(index-origin).days.to_numpy()/30]+[(index.dayofweek==day).astype(float) for day in range(1,7)])
    x=features(dates)
    penalty=np.eye(x.shape[1])*0.1
    penalty[0,0]=0
    beta=np.linalg.solve(x.T@x+penalty,x.T@y)
    return max(0.0,float((features([target])@beta)[0]))

rows=[]
candidate_rows=[]
skips=[]
for (device,kind),group in data.groupby(["device_id","source_kind"]):
    group=group[group.coverage_ratio>=0.8].copy()
    if not len(group):
        continue
    gaps=group.day.diff().dt.days.ne(1)
    group=group.loc[group.index[gaps][-1]:]
    if len(group)<56:
        skips.append({"device_id":device,"source_kind":kind,"reason":"need 56 consecutive covered days","available_days":len(group)})
        continue
    y=group.energy_wh.to_numpy(dtype=float)
    dates=pd.DatetimeIndex(group.day)
    cal_start,test_start=len(y)-28,len(y)-14
    candidates={}
    for model in ("seasonal_naive","ridge_calendar"):
        residuals=[abs(y[t]-prediction(y[:t],dates[:t],dates[t],model)) for t in range(cal_start,test_start)]
        radius=float(np.sort(residuals)[int(np.ceil((len(residuals)+1)*0.9))-1])
        preds=np.array([prediction(y[:t],dates[:t],dates[t],model) for t in range(test_start,len(y))])
        actual=y[test_start:]
        lo,hi=np.maximum(0,preds-radius),preds+radius
        metrics={"calibration_mae_wh":float(np.mean(residuals)),"holdout_mae_wh":float(np.mean(abs(actual-preds))),"holdout_rmse_wh":float(np.sqrt(np.mean((actual-preds)**2))),"holdout_interval_coverage":float(np.mean((actual>=lo)&(actual<=hi))),"holdout_mean_interval_width_wh":float(np.mean(hi-lo))}
        candidates[model]=(metrics["calibration_mae_wh"],radius)
        with mlflow.start_run(run_name=f"{device}-{kind}-{model}"):
            mlflow.log_params({"model":model,"source_kind":kind,"device_id":device,"holdout_days":14,"calibration_days":14,"interval_nominal":0.9})
            mlflow.log_metrics(metrics)
            mlflow.log_dict({"holdout_start":str(dates[test_start].date()),"holdout_end":str(dates[-1].date()),"selection":"calibration MAE only","predictions":[{"day":str(d.date()),"actual_wh":float(a),"prediction_wh":float(p),"lower_wh":float(l),"upper_wh":float(h)} for d,a,p,l,h in zip(dates[test_start:],actual,preds,lo,hi)]},"evaluation.json")
            mlflow.log_dict({"training_table":f"{ns}.gold_device_daily","source_kind":kind,"history_end":str(dates[-1].date()),"table_version":spark.sql(f"DESCRIBE HISTORY {ns}.gold_device_daily").limit(1).first()["version"]},"data-provenance.json")
    selected=min(candidates,key=lambda name:candidates[name][0])
    # Keep the unpromoted calibration winner separate from the dashboard baseline.
    for chosen,destination in (("seasonal_naive",rows),(selected,candidate_rows)):
        radius=candidates[chosen][1]
        extended_y,extended_dates=y.copy(),dates.copy()
        for step in range(1,8):
            target=dates[-1]+pd.Timedelta(days=step)
            value=prediction(extended_y,extended_dates,target,chosen)
            prediction_row=(device,kind,dates[-1].date(),target.date(),chosen,float(value),max(0.0,float(value-radius)),float(value+radius),0.9,step,"calibrated_one_day" if step==1 else "provisional_multi_day")
            destination.append(prediction_row if destination is rows else prediction_row+("unpromoted_research_candidate",))
            extended_y=np.append(extended_y,value)
            extended_dates=extended_dates.append(pd.DatetimeIndex([target]))
result_schema="device_id STRING,source_kind STRING,forecast_origin DATE,target_date DATE,model STRING,prediction_wh DOUBLE,lower_wh DOUBLE,upper_wh DOUBLE,interval_nominal DOUBLE,horizon_days INT,interval_status STRING"
spark.createDataFrame(rows,result_schema).write.mode("overwrite").option("overwriteSchema","true").saveAsTable(f"{ns}.forecast_daily")
spark.createDataFrame(candidate_rows,result_schema+",release_status STRING").write.mode("overwrite").option("overwriteSchema","true").saveAsTable(f"{ns}.candidate_forecast_daily")
print({"forecast_rows":len(rows),"release_status":"baseline_reference","model":"seasonal_naive","candidate_release_status":"unpromoted_research_candidate","skipped":skips,"interval_limit":"multi-day bounds are provisional; 90% is a target, observed holdout coverage is logged; measured-domain validation remains pending"})

# COMMAND ----------
anomaly_rows=[]
for (device,kind),group in data.groupby(["device_id","source_kind"]):
    observed={}
    history=[]
    for row in group.itertuples():
        prior=observed.get(row.day-pd.Timedelta(days=7))
        label=None if pd.isna(row.injected_anomaly_label) else bool(row.injected_anomaly_label)
        if row.coverage_ratio>=0.8 and prior is not None:
            residual=float(row.energy_wh)-prior
            if len(history)>=14:
                previous=np.array(history[-28:])
                center=float(np.median(previous))
                scale=max(1.0,1.4826*float(np.median(abs(previous-center))))
                score=abs(residual-center)/scale
                anomaly_rows.append((device,kind,row.day.date(),float(score),score>4,label,"seasonal_residual_mad",float(row.coverage_ratio)))
            history.append(residual)
        if row.coverage_ratio>=0.8:
            observed[row.day]=float(row.energy_wh)
anomaly_schema="device_id STRING,source_kind STRING,day DATE,score DOUBLE,is_alert BOOLEAN,injected_label BOOLEAN,method STRING,coverage_ratio DOUBLE"
spark.createDataFrame(anomaly_rows,anomaly_schema).write.mode("overwrite").option("overwriteSchema","true").saveAsTable(f"{ns}.anomaly_daily")
labelled=[row for row in anomaly_rows if row[1]=="simulated" and row[5] is not None]
tp=sum(row[4] and row[5] for row in labelled)
fp=sum(row[4] and not row[5] for row in labelled)
fn=sum(not row[4] and row[5] for row in labelled)
with mlflow.start_run(run_name="injected-anomaly-evaluation"):
    mlflow.log_params({"method":"seasonal_residual_mad","threshold":4,"label_scope":"explicit simulated labels only"})
    mlflow.log_metrics({"labelled_days":len(labelled),"true_positive":tp,"false_positive":fp,"false_negative":fn})
    if tp+fp: mlflow.log_metric("precision",tp/(tp+fp))
    if tp+fn: mlflow.log_metric("recall",tp/(tp+fn))
print({"scored_days":len(anomaly_rows),"labelled_simulated_days":len(labelled),"scope":"real-data alerts have no validated fault labels"})
