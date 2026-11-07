# R515 — require PostgreSQL commit evidence before an inbox acknowledgement

Reconciled the 24 acceptance areas against the current Content Control checklist,
implementation status, free deployment instructions, open PRs and workflow
results. Content Control main was `993f50f1135f12629f0905da207f0a39ffa50047`
([main gate](https://github.com/wecreates/content-control/actions/runs/42340001029)).
Money Factory main was `99a68ef902f88082a1126e170693eaeaea7a4a15`
([pin gate](https://github.com/wecreates/Money-factory/actions/runs/42340044588)).
No duplicate POD PR was open. The existing cross-repository gate pins that
Content Control revision and both publication flags remain literal `false`.

## Reproduction and repair

The receiver treated a resolved `COMMIT` query as durable acceptance. The
rollback-tag regression failed before the fix: a resolved `{command:'ROLLBACK'}`
could acknowledge an event. After validating the stored event digest, the
receiver now requires an own data property `command` whose value is `COMMIT`.
Absent, nonmatching, inherited or executable evidence cannot acknowledge the
event. The unverified result destroys the client without sending more SQL and
the HTTP boundary returns a redacted retryable 503. A matching unchanged event
can be retried through the existing digest-based replay guard.

Local Money Factory Node: 291 passed, one disposable-PostgreSQL case skipped
because no test database was configured. Python: 81 passed. Diff and Node syntax
checks passed. The existing hosted bridge case now induces a real PostgreSQL
transaction error immediately before COMMIT and checks the ROLLBACK tag, no
acknowledgement, client discard, zero retained rows and an exact-event retry
resulting in one retained row. Exact-head hosted results and merge readback are
recorded in the implementation PR; the local skip is not a live test result.

## Deployment and acceptance boundaries

The authorized free Render worker was live on deploy `dep-dbnar0nb9u1s73cglheg`
at the Content Control revision above. This receiver-only change neither
requires nor triggers a Content Control rollout. No authorized live Money
Factory inbox endpoint was available; mounting and live delivery remain
unverified. All 24 acceptance areas remain open. No changed database-admin
access path was identified or retried. No publication switch, marketplace
action, production database write, paid resource, secret access or network
permission was changed. Scheduled verification is not an always-on worker.
