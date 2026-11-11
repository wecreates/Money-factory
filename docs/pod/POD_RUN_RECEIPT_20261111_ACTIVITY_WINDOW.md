# Exact activity observation windows — November 11, 2026

Fresh main heads: CC42eade200a481445e68d9d92a6f4ec34bc992be3 and
MF75128cdcb29584d09a742978bf85391c4fec5c43. Open PRs/workflows inspected;
no duplicate POD job/PR and no repository AGENTS.md. Current checklist and
free-deployment blobs580f8027d946fc34d4ecc28b208652f01ca5e4ac and
e4f64cc489bb4fdbc2a1e1f235f2b29507fd7676 read through GitHub; status blob
ee5017b86f4b13f8d597c43b4ab09ee3f21ca6db matched retained local source
before reading its active section. An obsolete scratch path failed; current
workspace execution succeeded. No missing-path attempt is counted as a test.

The SQL activity query used microsecond transaction_timestamp boundaries while
node-postgres native Dates expose only milliseconds. Records near either edge
could therefore be counted against a subtly different window from the receipt.
Both boundaries now derive from date_trunc('milliseconds',transaction_timestamp()).
The same repeatable-read snapshot,24-hour duration,start-inclusive/end-exclusive
predicate,platform scope,count strings,release/deadline checks and all false
capacity/acceptance/publication indicators remain unchanged. No record timestamps
are altered, rounded or rewritten; this defines the observation cutoff precisely.

The new unit regression failed against the old SQL, then passed after repair.
Local activity suite18 PASS; new PostgreSQL case1 SKIP because no disposable URL
is configured locally. Hosted tests must verify it before merge. The PostgreSQL
case creates only session-local temporary tables in the existing workflow test
database and checks server precision plus inclusive-start/exclusive-end events.
It never uses production data, schema migrations, live accounts or secrets.

Render metadata still reports existing free Docker service with live deploy
dep-dbqb25m0tbcc7393v1sg on baseline42eade200a481445e68d9d92a6f4ec34bc992be3,
finished2026-11-11T18:17:56.221659Z. The new repair is not live until verified
rollout. Latest POD integration on merged main passed. Live hosted-review smoke
43079452477 is BLOCKED on caption_receipt_not_pass and caption binding; that
separate video lane is preserved, not accepted, bypassed or repaired here.

All24 acceptance areas remain OPEN. This is accurate historical activity
telemetry, not measured100/1000 unique concepts/day, current independent QA,
production authority, live preflight, retained backup/restore or launch approval.
Both publication flags remain false. No credible changed DB administration path,
so no retry. No new paid resources, credentials, messages, network widening,
social-vault access, marketplace action or fabricated acceptance. Free web hosting
is not an always-on worker. Record final exact-head CI,merge and rollout evidence
in the resulting PRs. Do not disable completion automation without completion.
