# POD polling timer bound — November 10, 2026

Pin the exact passing Content Control merge from PR #1179. The worker now rejects
polling delays above Node's signed 32-bit timer limit before callbacks or database
work, avoiding Node's fallback to 1 ms polling. The explicit cross-repository
worker check includes overflow admission and cancellable minimum/default/maximum
delays, alongside the existing worker lifecycle regressions.

Local bridge tests: 322 passed, one disposable PostgreSQL test skipped because
no local test database was configured. Hosted workflow and exact merge evidence
are recorded on the PR. No duplicate dispatch is required: the PR runs its gate.

All 24 live acceptance areas remain open. Publication stays held for explicit
owner approval. No production database, marketplace, service activation,
credential, network access or continuously running worker is established here.
