# Appliance energy service brief

The client is a fictional appliance-service business. Its operations manager needs to decide which monitored devices deserve investigation and how much energy demand to expect next week. This is a consulting case, not a completed customer engagement.

The manager receives energy totals, observation coverage, stale-device status, gap counts, forecast ranges and an inspection queue. Energy calculations separate valid counter deltas from energy spanning unknown intervals. A tariff could support a labelled cost scenario; no bill or saving is inferred without measurements and an intervention comparison.

| KPI | Definition and decision |
|---|---|
| Observed energy | Valid consecutive counter differences over covered intervals; ranks usage |
| Unallocated energy | Counter increases across excessive gaps; identifies uncertain totals |
| Coverage | Observed interval seconds divided by the eligible window; qualifies comparisons |
| Command outcome | Confirmed, pending, expired, superseded or unknown; guides operator follow-up |
| Forecast error | Temporal holdout error versus seasonal-naive; decides model promotion |
| Interval quality | Coverage and width on future observations; qualifies planning ranges |
| Alert usefulness | Precision/recall on explicitly labelled injected anomalies; evaluates the test scenario |

Operational observations start with simulation. Historical analysis can ingest a bounded, attributed REFIT sample. Simulated, estimated, measured and public-dataset cohorts remain distinct. Historical UK households do not establish behaviour of any specific manufacturer or Indian consumer population.

Deliverables are a reproducible data path, energy report, evaluated forecasting and SQL query modes, recommendation memo and presentation. Success means an auditable decision trail and honest uncertainty. Prevented failures and reduced energy consumption are hypotheses for a later measured pilot.
