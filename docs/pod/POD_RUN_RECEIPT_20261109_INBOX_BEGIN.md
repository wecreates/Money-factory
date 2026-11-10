# November 9, 2026 — verify that the event inbox transaction opened

Reviewed both repository heads, open PRs, latest POD workflow results, the
24-area checklist, implementation status, free deployment runbook and authorized
Render worker. Content Control `5c4256e917aacfe9f1e83140fc42bb354931caf7` passed its
main gate and was live on `dep-dbp78ejbc2fs73b7toc0`. Money Factory
`94f201272d53295bd2d626a04c8303e77bfc539e` already pinned that consumer. No duplicate
POD PR was open and no changed production database-admin path was identified.

The receiver previously treated any resolved BEGIN as a transaction. An
unverified adapter result could therefore let timeout setup and the inbox
insert run without a managed transaction. The baseline regression reproduced
that success. The receiver now requires the exact own, inert BEGIN command tag
before further SQL. A different, missing or malformed result discards the
connection, sends no rollback or insert, and returns the existing redacted 503.
The same validator preserves exact COMMIT evidence and rejects an array carrying
a forged command property. No production data was used in these tests.

The existing disposable PostgreSQL bridge substitutes a real SELECT result for
BEGIN, checks that the event is absent after refusal and the connection is
discarded, then retries on a healthy pool and requires one stored row. Local
Node verification passed 300 tests with one disposable PostgreSQL skip. Hosted
exact-head results and merge readback are recorded in the implementation PR.

Both publication switches remain false; no deployment, configuration, network or
marketplace action was taken. The live Money Factory inbox was not available for
verification. All 24 live acceptance areas remain open. Scheduled verification
does not establish an always-on worker.
