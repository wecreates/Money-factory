# Native outbox shutdown bridge — November 10, 2026

Pin the exact passing Content Control PR #1180 merge. Its outbox runtime checks
native cancellation and waits using an owned timer signal, so delivery callbacks
that shadow signal members and synthetic abort events cannot fail a healthy loop.
The cross-repository gate explicitly runs these shutdown regressions alongside
the unchanged delivery, event bridge, PostgreSQL and production/review checks.

Exact workflow, tests, merge and Render observations are recorded on this PR.
All 24 live acceptance areas remain OPEN; no real authority, production database,
marketplace, backup, revenue, capacity or continuous worker operation is proven.
Publication/service settings, credentials, network access and free resources
are unchanged. Fixtures are not live acceptance and no duplicate job is needed.
