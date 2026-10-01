-- Run after selecting the deployed catalog and appliance_energy schema.
-- Every count below must be zero before claiming a successful cloud proof.
SELECT count(*) AS duplicate_event_ids FROM (
  SELECT event_id FROM silver_telemetry GROUP BY event_id HAVING count(*) > 1
);
SELECT count(*) AS duplicate_device_boot_sequence FROM (
  SELECT device_id,boot_id,sequence_no FROM silver_telemetry
  GROUP BY device_id,boot_id,sequence_no HAVING count(*) > 1
);
SELECT count(*) AS invalid_energy_rows FROM gold_device_daily
WHERE energy_wh < 0 OR coverage_ratio < 0 OR coverage_ratio > 1;

-- Capture these aggregates, rerun the same immutable landing directory, compare.
SELECT source_kind,count(*) AS days,sum(energy_wh) AS allocated_wh,
sum(unallocated_energy_wh) AS gap_counter_wh FROM gold_device_daily GROUP BY source_kind;
SELECT * FROM gold_quality;

-- Trace energy_wh from gold_device_daily through gold_device_hourly and
-- telemetry_intervals in Catalog Explorer. Inspect column mappings there.
