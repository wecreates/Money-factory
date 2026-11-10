# November 9, 2026 — verify diagnostic commit evidence with the POD consumer

The Content Control diagnostic repair requires explicit PostgreSQL COMMIT
evidence before returning metrics or recorded activity. A resolved ROLLBACK tag
discards the client and returns no successful report. See
[Content Control #1154](https://github.com/wecreates/content-control/pull/1154)
for the baseline reproduction, disposable PostgreSQL test, and rollout readback.
The merged consumer revision is `5c4256e917aacfe9f1e83140fc42bb354931caf7`.

The existing cross-repository gate exercises the operational-health and capacity
regressions alongside the authority, inbox, production and review checks. No new
workflow, job, service, configuration or migration was added. Local Money Factory
verification against the patched consumer passed 298 Node tests, one disposable
PostgreSQL skip, and 81 Python tests. Exact hosted results and pin are in the PR.

Both publication flags remain false. This verifies source compatibility, not a
live authority mount, measured throughput, backup recovery or release acceptance.
The 24 live acceptance areas remain open.
