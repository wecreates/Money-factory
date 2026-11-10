# POD inbox receipt: verify the stored observation

Money Factory base `9cd455753e54fdaeebc34dc35cb6cba9c07d9221` accepted a
signed replay when the stored digest matched, even if the stored observation
did not. The receiver now requires the matching digest and exact SQL boolean
confirmation of JSONB content equality for the selected event ID. JSONB equality
avoids rehashing keys in PostgreSQL's storage order. A conflict leaves the
stored row unchanged and returns redacted HTTP 409; unverified result shape
returns 503. This does not authorize automatically repairing a conflicting row.

The same receiver also checks the timestamp's primitive type before parsing.
A signed timestamp object with non-callable conversion fields previously
returned 503 instead of 400. It now returns a redacted 400 before checkout.

Local HTTP regressions reproduced both incorrect statuses before the repair.
The cross-repository gate pins Content Control
`fcacb24a13c9f8f92c4f6827e6796d96a2920b91` and exercises the real sender
and receiver against a disposable PostgreSQL 18 database: after losing a
receipt, a fixture-only edit changes the observation without changing the digest.
The test requires 409, no sender delivery, no overwrite, and one unchanged-ID
delivery after restoring the original fixture. The pull request records the
exact run and result. Both publication flags are false in this gate.

This is code and test evidence only. No live authority, database checkout,
marketplace, financial settlement, or production acceptance was verified.
No changed path for database administration was identified. The existing
free Render service was observed live at the pinned Content Control commit;
that observation does not verify Money Factory deployment, an always-on
worker, or readiness. All 24 live acceptance areas remain open.
