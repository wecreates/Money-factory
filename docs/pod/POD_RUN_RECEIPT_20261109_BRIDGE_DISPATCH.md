# November 9, 2026 — prepare the Money Factory host mount for both POD routes

Reviewed the current 24-area checklist, implementation status and free deployment
runbook, open PRs and recent CI. Money Factory `b70b62186baf3b169885db8da7d0c6caaea20bce`
included the passing grant-wire repair. Content Control main and the authorized
free Render deployment `dep-dbp5236417fc7398oba0` were at
`5303a4719d69f19d9ff852048645759513936e27`. The existing cross-repository pin at
`156931462d7ecc1d51798a936f7192e6884390b7` was retained; the POD consumer and
bridge modules were unchanged at the deployed revision. No duplicate PR or job
was opened, and no database administration path materially changed.

Both POD handlers existed as standalone modules, but the host had no shared
mount contract to enforce exact routing and cross-role credential separation.
The new dispatcher accepts explicit non-aliased raw paths and refuses reuse of
the bearer, grant-signing or outbox signing key. It hands other routes back to
the host and does not create infrastructure or an approval source. Existing
handlers still own their authentication and timeout rules.

Local HTTP tests verify path and credential isolation, no fallback after a POD
auth failure, and redacted errors. The existing hosted disposable PostgreSQL
case now mounts both handlers on one loopback server and verifies a task-bound
grant and subsequent revocation through Content Control's real grant client,
plus event delivery and deduplication through its outbox sender. Hosted results
and merge readback are recorded in the implementation PR. This is not live
authority, revocation, marketplace, production database or deployment evidence.

No TLS ingress or live loader was available to mount; no changes were made to
Render, credentials, publication, network permissions or paid resources. Both
publication flags remain false. All 24 live acceptance areas remain open.
