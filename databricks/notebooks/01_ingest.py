# Databricks notebook source
# MAGIC %md
# MAGIC # Immutable file ingestion
# MAGIC Dated account-execution evidence is recorded in the component VALIDATION.md.

# COMMAND ----------
import re
from pyspark.sql import functions as F
from delta.tables import DeltaTable

for name, default in (("catalog", "workspace"), ("schema", "appliance_energy"), ("landing_path", "")):
    dbutils.widgets.text(name, default)
catalog, schema, landing = (dbutils.widgets.get(name) for name in ("catalog", "schema", "landing_path"))
assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in (catalog, schema)), "Invalid catalog/schema"
assert landing.startswith("/Volumes/") and ".." not in landing, "Use a UC volume landing directory"
namespace = f"{catalog}.{schema}"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
spark.sql("SET TIME ZONE 'UTC'")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {namespace}.bronze_events (
  source_hash STRING, source_file STRING, row_number BIGINT, raw_json STRING
) USING DELTA""")

# Bounded immutable batches are intentional: broker connectivity is outside this adapter.
files = (spark.read.format("binaryFile").option("pathGlobFilter", "*.jsonl")
         .option("recursiveFileLookup", "true").load(landing))
assert files.where("length > 16777216").limit(1).count() == 0, "Split input batches below 16 MiB"
rows = (files.select(F.sha2("content", 256).alias("source_hash"), F.col("path").alias("source_file"),
                     F.posexplode(F.split(F.decode("content", "UTF-8"), "\n")).alias("line_index", "raw_json"))
        .where(F.length(F.trim("raw_json")) > 0)
        .select("source_hash", "source_file", (F.col("line_index") + 1).cast("long").alias("row_number"), "raw_json")
        .dropDuplicates(["source_hash", "row_number"]))
(DeltaTable.forName(spark, f"{namespace}.bronze_events").alias("target")
 .merge(rows.alias("incoming"), "target.source_hash=incoming.source_hash AND target.row_number=incoming.row_number")
 .whenNotMatchedInsertAll().execute())
print({"bronze_rows": spark.table(f"{namespace}.bronze_events").count(), "source": "immutable normalized protocol v1 JSONL"})
