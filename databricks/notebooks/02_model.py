# Databricks notebook source
# MAGIC %md
# MAGIC # Validate identities, preserve conflicts and derive energy with coverage
# MAGIC Spark SQL references registered tables so UC can capture supported lineage.

# COMMAND ----------
import re
from pyspark.sql import functions as F, Window
from delta.tables import DeltaTable

for name, default in (("catalog", "workspace"), ("schema", "appliance_energy"), ("max_gap_seconds", "120")):
    dbutils.widgets.text(name, default)
catalog, schema = (dbutils.widgets.get(name) for name in ("catalog", "schema"))
assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in (catalog, schema))
max_gap = float(dbutils.widgets.get("max_gap_seconds"))
assert 0 < max_gap <= 86400
ns = f"{catalog}.{schema}"
spark.sql("SET TIME ZONE 'UTC'")
event_schema = "schema_version INT,event_id STRING,device_id STRING,boot_id STRING,sequence BIGINT,event_time STRING,source_kind STRING,power_w DOUBLE,energy_wh_total DOUBLE,firmware_version STRING,quality_flags ARRAY<STRING>,received_at STRING"
bronze = spark.table(f"{ns}.bronze_events")
parsed = bronze.withColumn("event", F.from_json("raw_json", event_schema)).select("source_hash", "source_file", "row_number", "raw_json", "event.*")
uuid_pattern = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
valid = ((F.col("schema_version") == 1) & F.col("event_id").rlike(uuid_pattern) & F.col("boot_id").rlike(uuid_pattern)
         & F.col("device_id").rlike(r"^[A-Za-z0-9_-]{1,64}$") & (F.col("sequence") >= 0)
         & F.col("source_kind").isin("simulated", "measured", "estimated", "public_dataset")
         & (F.col("power_w") >= 0) & ~F.isnan("power_w") & (F.col("power_w") != float("inf"))
         & (F.col("energy_wh_total") >= 0) & ~F.isnan("energy_wh_total") & (F.col("energy_wh_total") != float("inf"))
         & F.col("event_time").rlike(r"(Z|\+00:00)$") & F.col("received_at").rlike(r"(Z|\+00:00)$")
         & F.try_to_timestamp("event_time").isNotNull() & F.try_to_timestamp("received_at").isNotNull()
         & F.col("quality_flags").isNotNull() & (F.size("quality_flags") <= 32)
         & F.col("firmware_version").isNotNull() & (F.length("firmware_version") > 0)
         & (F.size(F.json_object_keys("raw_json")) == 12))
invalid = parsed.where(~F.coalesce(valid, F.lit(False))).withColumn("reason", F.lit("invalid_protocol_event"))
candidate = (parsed.where(F.coalesce(valid,F.lit(False))).withColumnRenamed("sequence","sequence_no")
             .withColumn("event_id",F.lower("event_id")).withColumn("boot_id",F.lower("boot_id"))
             .withColumn("event_time",F.try_to_timestamp("event_time")).withColumn("received_at",F.try_to_timestamp("received_at"))
             .withColumn("quality_flags_json",F.to_json("quality_flags")))
payload_columns = ["schema_version","event_id","device_id","boot_id","sequence_no","event_time","source_kind","power_w","energy_wh_total","firmware_version","quality_flags_json"]
candidate = candidate.withColumn("payload_hash",F.sha2(F.to_json(F.struct(*payload_columns)),256))
silver_columns = ["schema_version","event_id","device_id","boot_id","sequence_no","event_time","received_at","source_kind","power_w","energy_wh_total","firmware_version","quality_flags_json","payload_hash"]
spark.sql(f"""CREATE TABLE IF NOT EXISTS {ns}.silver_telemetry (
 schema_version INT,event_id STRING,device_id STRING,boot_id STRING,sequence_no BIGINT,event_time TIMESTAMP,
 received_at TIMESTAMP,source_kind STRING,power_w DOUBLE,energy_wh_total DOUBLE,firmware_version STRING,
 quality_flags_json STRING,payload_hash STRING) USING DELTA""")
existing = spark.table(f"{ns}.silver_telemetry")

# Previously accepted evidence takes precedence over every later file hash.
known_id = existing.select(F.col("event_id").alias("known_event_id"),F.col("payload_hash").alias("known_hash"))
known_slot = existing.select("device_id","boot_id","sequence_no",F.col("event_id").alias("slot_event_id"))
candidate_columns = candidate.columns
checked = candidate.join(known_id,candidate.event_id==known_id.known_event_id,"left").join(known_slot,["device_id","boot_id","sequence_no"],"left")
conflicts = checked.where("(known_event_id IS NOT NULL AND payload_hash != known_hash) OR (slot_event_id IS NOT NULL AND event_id != slot_event_id)").withColumn("reason",F.lit("conflicting_existing_identity"))
candidate = checked.where("known_event_id IS NULL AND slot_event_id IS NULL").select(*candidate_columns)

# Choose stable winners only among identities never accepted before.
event_first = candidate.withColumn("_order",F.row_number().over(Window.partitionBy("event_id").orderBy("source_hash","row_number")))
winners = event_first.where("_order=1").select("event_id",F.col("payload_hash").alias("winner_hash"))
within_conflicts = candidate.join(winners,"event_id").where("payload_hash != winner_hash").withColumn("reason",F.lit("conflicting_event_id"))
candidate = event_first.where("_order=1").drop("_order")
slot_order = Window.partitionBy("device_id","boot_id","sequence_no").orderBy("source_hash","row_number")
candidate = candidate.withColumn("_slot_order",F.row_number().over(slot_order))
slot_conflicts = candidate.where("_slot_order>1").withColumn("reason",F.lit("conflicting_device_boot_sequence"))
candidate = candidate.where("_slot_order=1").drop("_slot_order")
accepted = candidate.select(*silver_columns)
qcols=["source_hash","row_number","event_id","reason","raw_json"]
quarantined=invalid.select(*qcols).unionByName(within_conflicts.select(*qcols)).unionByName(slot_conflicts.select(*qcols)).unionByName(conflicts.select(*qcols))
# A physical row stays one quarantine record even when later silver state changes
# its classification from an intra-batch conflict to an existing-identity conflict.
quarantined=quarantined.withColumn("quarantine_id",F.sha2(F.concat_ws(":","source_hash","row_number"),256)).dropDuplicates(["quarantine_id"])
spark.sql(f"CREATE TABLE IF NOT EXISTS {ns}.quarantine (source_hash STRING,row_number BIGINT,event_id STRING,reason STRING,raw_json STRING,quarantine_id STRING) USING DELTA")
(DeltaTable.forName(spark,f"{ns}.quarantine").alias("t").merge(quarantined.alias("s"),"t.quarantine_id=s.quarantine_id").whenNotMatchedInsertAll().execute())
(DeltaTable.forName(spark,f"{ns}.silver_telemetry").alias("t").merge(accepted.alias("s"),"t.event_id=s.event_id").whenNotMatchedInsertAll().execute())

# COMMAND ----------
spark.sql(f"""CREATE OR REPLACE TABLE {ns}.telemetry_intervals USING DELTA AS
 WITH previous AS (SELECT *,
 lag(boot_id) OVER w AS previous_boot, lag(sequence_no) OVER w AS previous_sequence,
 lag(event_time) OVER w AS previous_time, lag(energy_wh_total) OVER w AS previous_energy,
 max(energy_wh_total) OVER (PARTITION BY device_id,source_kind,boot_id ORDER BY event_time,event_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS energy_anchor
 FROM {ns}.silver_telemetry
 WINDOW w AS (PARTITION BY device_id,source_kind ORDER BY event_time,event_id)),
 differences AS (SELECT *,(unix_micros(event_time)-unix_micros(previous_time))/1000000.0 AS seconds,
 energy_wh_total-energy_anchor AS delta_wh FROM previous)
 SELECT *, CASE WHEN previous_time IS NULL THEN 'first'
 WHEN boot_id!=previous_boot THEN 'reset'
 WHEN seconds<=0 OR sequence_no<=previous_sequence OR delta_wh < -0.00000001 THEN 'invalid'
 WHEN seconds>{max_gap} OR sequence_no!=previous_sequence+1 OR previous_energy<energy_anchor THEN 'gap'
 ELSE 'covered' END AS interval_status FROM differences""")

spark.sql(f"""CREATE OR REPLACE TABLE {ns}.gold_device_hourly USING DELTA AS
 WITH readings AS (SELECT device_id,source_kind,date_trunc('hour',event_time) AS hour,
 count(*) AS reading_count,avg(power_w) AS mean_power_w,max(power_w) AS peak_power_w,
 sum(CASE WHEN interval_status='gap' THEN greatest(delta_wh,0) ELSE 0 END) AS unallocated_energy_wh,
 sum(CASE WHEN interval_status='gap' THEN 1 ELSE 0 END) AS gap_count,
 sum(CASE WHEN interval_status='reset' THEN 1 ELSE 0 END) AS reset_count,
 sum(CASE WHEN interval_status='invalid' THEN 1 ELSE 0 END) AS invalid_interval_count,
 min(CASE WHEN array_contains(from_json(quality_flags_json,'ARRAY<STRING>'),'evaluation_label_normal') THEN 1 ELSE 0 END)=1 AS labelled_normal,
 max(CASE WHEN array_contains(from_json(quality_flags_json,'ARRAY<STRING>'),'injected_anomaly') THEN 1 ELSE 0 END)=1 AS labelled_anomaly
 FROM {ns}.telemetry_intervals GROUP BY device_id,source_kind,date_trunc('hour',event_time)),
 expanded AS (SELECT *,explode(sequence(date_trunc('hour',previous_time),date_trunc('hour',event_time),INTERVAL 1 HOUR)) AS hour
 FROM {ns}.telemetry_intervals WHERE interval_status='covered'),
 allocated AS (SELECT *,greatest(0,unix_micros(least(event_time,hour+INTERVAL 1 HOUR))-unix_micros(greatest(previous_time,hour)))/1000000.0 AS overlap_seconds FROM expanded),
 energy AS (SELECT device_id,source_kind,hour,sum(greatest(delta_wh,0)*overlap_seconds/seconds) AS energy_wh,
 sum(overlap_seconds) AS coverage_seconds FROM allocated WHERE overlap_seconds>0 GROUP BY device_id,source_kind,hour)
 SELECT coalesce(r.device_id,e.device_id) AS device_id,coalesce(r.source_kind,e.source_kind) AS source_kind,
 coalesce(r.hour,e.hour) AS hour,CAST(coalesce(e.energy_wh,0) AS DECIMAL(24,8)) AS energy_wh,
 CAST(coalesce(r.unallocated_energy_wh,0) AS DECIMAL(24,8)) AS unallocated_energy_wh,coalesce(e.coverage_seconds,0) AS coverage_seconds,
 coalesce(r.reading_count,0) AS reading_count,r.mean_power_w,r.peak_power_w,
 coalesce(r.gap_count,0) AS gap_count,coalesce(r.reset_count,0) AS reset_count,
 coalesce(r.invalid_interval_count,0) AS invalid_interval_count,
 coalesce(r.labelled_normal,true) AS labelled_normal,coalesce(r.labelled_anomaly,false) AS labelled_anomaly
 FROM readings r FULL OUTER JOIN energy e ON r.device_id=e.device_id AND r.source_kind=e.source_kind AND r.hour=e.hour""")

spark.sql(f"""CREATE OR REPLACE TABLE {ns}.gold_device_daily USING DELTA AS
 SELECT device_id,source_kind,CAST(hour AS DATE) AS day,sum(energy_wh) AS energy_wh,
 sum(unallocated_energy_wh) AS unallocated_energy_wh,sum(coverage_seconds) AS coverage_seconds,
 least(1.0,sum(coverage_seconds)/86400.0) AS coverage_ratio,sum(reading_count) AS reading_count,
 sum(mean_power_w*reading_count)/nullif(sum(reading_count),0) AS mean_power_w,max(peak_power_w) AS peak_power_w,
 sum(gap_count) AS gap_count,sum(reset_count) AS reset_count,sum(invalid_interval_count) AS invalid_interval_count,
 CASE WHEN bool_or(labelled_anomaly) THEN true WHEN bool_and(labelled_normal) AND sum(reading_count)>0 THEN false ELSE NULL END AS injected_anomaly_label
 FROM {ns}.gold_device_hourly GROUP BY device_id,source_kind,CAST(hour AS DATE)""")
spark.sql(f"""CREATE OR REPLACE TABLE {ns}.gold_quality USING DELTA AS SELECT
 (SELECT count(*) FROM {ns}.bronze_events) AS bronze_rows,
 (SELECT count(*) FROM {ns}.silver_telemetry) AS accepted_events,
 (SELECT count(*) FROM {ns}.quarantine) AS quarantined_rows,
 coalesce(sum(gap_count),0) AS gap_count,coalesce(sum(invalid_interval_count),0) AS invalid_interval_count,
 coalesce(sum(unallocated_energy_wh),0) AS unallocated_energy_wh FROM {ns}.gold_device_daily""")
assert spark.sql(f"SELECT count(*) FROM {ns}.gold_device_daily WHERE energy_wh<0 OR coverage_ratio<0 OR coverage_ratio>1").first()[0]==0
display(spark.table(f"{ns}.gold_quality"))
