# Verified outbox monitoring count bridge — November 10, 2026

Pin the exact passing Content Control #1181 merge. The explicit outbox check now
includes malformed count, executable result, cursor retention and clean retry
regressions. Invalid results must not corrupt counters or claim healthy delivery;
the existing bridge and PostgreSQL production/review checks remain enabled.

Exact tests, workflow, merge and Render observations are recorded on the PR.
All 24 live acceptance areas remain OPEN. These checks do not prove an adapter's
reported count occurred or establish real revenue, live authority, database,
backup, marketplace, capacity or continuous worker operation. No publication or
service activation, credentials, network expansion or paid resource is added.
