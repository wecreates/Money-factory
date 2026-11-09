# November 9, 2026 — reject grants the consumer cannot verify

Reviewed the Content Control checklist, implementation status and free deployment
runbook, both repository heads/open PRs/workflows, and the authorized free Render
worker. Content Control `156931462d7ecc1d51798a936f7192e6884390b7` was live on
`dep-dbp44erbc2fs73b3nb80`; its main integration gate passed. Money Factory
`1929fd3ed42481fc3394f922470cda66ddc6d755` already pinned that consumer, and
the preceding cross-repository workflow passed. No duplicate POD PR was open.

The issuer signed unsafe JSON integers that the pinned consumer rejected as
`ENVELOPE_JSON_UNSAFE_INTEGER`. The direct signer could also cross the consumer's
262,144-byte payload limit because the snapshot budget counted text but not all
serialized framing. Both new regression tests failed before repair. Strict
snapshot copying now rejects unsafe integers; valid fractions and safe boundary
integers round-trip. The signer also checks the actual UTF-8 payload size before
HMAC, while the existing HTTP response limit stays in force. A localhost HTTP
test verifies that invalid snapshot data yields redacted `409 GRANT_BLOCKED` and
that a corrected snapshot returns a valid production-only grant.

Local: 296 Node tests passed, one disposable PostgreSQL case skipped; 81 Python
tests passed. Syntax and diff checks passed. Exact hosted gate and merged readback
are recorded in the implementation PR. The workflow keeps the existing consumer
pin and both publication switches false.

No live issuer, real approval or market submission was exercised. No credible
changed production database-admin path was identified or retried. No deployment
settings, paid resources or network permissions were changed. This is source and
test evidence, not live authority or always-on execution. All 24 live acceptance
areas remain open.
