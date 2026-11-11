# Bind diagnostics to dedicated public POD tables — November 11, 2026

Fresh heads CCfd9e6a14bdfabbdaefcfd32916b6c668bcc3763b and
MFe2759a30537b78768237784816e142b58f963db2. Current heads,open PRs,workflow
results and authorized Render service read; no duplicate POD PR/job or AGENTS.md.
Checklist/free-deployment blobs580f8027d946fc34d4ecc28b208652f01ca5e4ac and
e4f64cc489bb4fdbc2a1e1f235f2b29507fd7676 read through GitHub; status blob
ee5017b86f4b13f8d597c43b4ab09ee3f21ca6db matched the retained copy before
reading its active status. All24 live acceptance areas remain OPEN.

Both direct read-only activity and metrics diagnostics used unqualified POD
table names. A session-local temporary table or changed search_path could
therefore redirect reads away from the dedicated public tables. Explicitly
qualify all9 FROM/JOIN references with public. No search_path,roles,permissions,
schema,migrations,DDL or data changes are introduced in the production code.
The transaction,timeout,cleanup,count validation and acceptance/publication
indicators remain unchanged. This does not assert an observed live compromise.

Two new regressions failed before repair for all3 activity and6 metrics table
references. After repair, focused local diagnostics20 PASS; PostgreSQL1 SKIP
because no disposable database is configured locally. Attempts to run the wider
operational suite in a minimal source snapshot failed module loading for absent
support files, not an executed assertion; no local pass is claimed for it.
Its SQL-specific mocks now match the same schema-qualified table references.
Complete hosted checks must pass before merge.

The PostgreSQL regression now creates a uniquely named database only on the
existing local disposable CI PostgreSQL instance, guarded by local host/test
database allowlists. Its exact generated database is dropped after closing its
client. No live database or provider resources are used. Public fixture tables
contain small synthetic rows; misleading TEMP aliases and search_path=pg_temp
must not alter activity,queue,storage,financial or health observations. The
deterministic microsecond source retains prior window edge/precision coverage.
Production activity stays read-only; fixture writes happen before diagnosis.

Render currently lists live dep-dbqc5eqvcj2c73en394g on baselinefd9e6a14,
finished2026-11-11T19:34:08.241397Z, on the existing free Docker service. New
repair is not deployed until separately observed. Latest merged-main POD gate
passes. Runtime provenance failure43090881923 is a separate video asset hash
mismatch,not an SBOM/POD pass to manufacture; preserve its guard. No fresh public
runtime probe yet. No changed DB administration path,therefore no retry.

No paid resources,secrets,messages,social-vault access,network widening,accounts,
rights clearances,marketplace actions,finance acceptance or throughput invented.
Keep both publication flags false. Passing disposable tests and liveness do not
establish retained backup/recovery,live authority/current grants,production
preflight,independent QA,owner-phone acceptance,100/1000 measured capacity or
controlled release. A sleeping free service is not a continuous self-hosted
worker. Record final exact-head tests,merges and rollout evidence in the PRs.
