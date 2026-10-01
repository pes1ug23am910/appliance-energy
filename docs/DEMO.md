# Two demonstrations

Use synthetic data for both demonstrations. The fictional client and the software simulator are explicit parts of the presentation; a confirmed simulated state does not establish physical actuation or energy savings.

## Reliable appliance control

1. Follow the root quick start, run the seven transport checks, and start the [Flutter console](../mobile/README.md). Keep one simulated device running in a separate terminal:

   ```sh
   uv run --project simulator python scripts/with_env.py uv run --project simulator appliance-simulator run --count 1 --interval 2 --duration 300
   ```

2. Connect the console to the local API with the token from your ignored environment file. Select the device and inspect desired/reported revision and freshness.
3. Pause the backend with `docker compose pause backend`. Set an absolute power/speed value in the console. Observe the queued or uncertain outcome and its command UUID.
4. Reload the console at the same browser origin. The token must be entered again, while the pending command retains its original UUID and payload.
5. Resume with `docker compose unpause backend`. Reconcile the pending command. A matching device report establishes confirmation; an HTTP success alone does not.
6. Explain the failure boundary: dispatch can be retried, so absolute state and revision fencing make duplicates safe. A physical exactly-once guarantee would require additional evidence that this simulator does not supply.

The automated browser recovery test follows this path without leaving the service paused. See [mobile validation](../mobile/VALIDATION.md) and [the protocol](../contracts/PROTOCOL.md). Finish any manual demo by unpausing the backend, even if an earlier step fails.

## Energy investigation and forecast

1. Read the one-page [business brief](BRIEF.md), then run `uv run --locked python scripts/run_demo.py` from `analytics`.
2. Inspect source labels and coverage before comparing devices. The fixture contains two synthetic 70-day histories, plus partial endpoint rows. Explain why a gap is not zero consumption and cumulative energy counters cannot be summed directly.
3. Run the [Databricks bundle](../databricks/README.md) on the same immutable input. Compare the daily gold export to the local oracle. Rerun identical input and verify stable identity counts and energy, then use the separate two-phase quality fixture to repair a late missing sequence.
4. Open the three-page [Power BI project](../powerbi/README.md) and refresh. The reference overview displays 221.278 kWh, 98.6% mean coverage and two devices. Inspect the coverage rows and the 14 device-level forecasts, including provisional longer horizons.
5. Inspect the seasonal-naive and ridge holdouts in MLflow. Keep the seasonal baseline: the recorded challenger performs worse. Selected Unity Catalog column-lineage paths and MLflow input-table versions provide complementary provenance.
6. Ask `total energy` through the deterministic query route. If a local model is already installed, demonstrate its guarded SQL route and the saved wrong-answer evaluation. Explain the retained Wh/kWh failure instead of treating safe execution as a correct answer.
7. Close with the [recommendation memo](RECOMMENDATION.md) and [six-slide presentation](presentation.html): a measured pilot with prospective evaluation is the next decision.

The Databricks job is on demand, with a single writer. Keep local CSV refresh, operator-attested cloud Desktop refresh, and untested hosted Power BI refresh distinct. Stop the SQL warehouse when the demonstration is finished. Physical hardware and production tenancy remain outside the demonstrated software boundary.
