# Listing reconciliation read identity

The bridge gate pins the Content Control main revision from
[PR 1165](https://github.com/wecreates/content-control/pull/1165) and exercises
signed listing reconciliation, including an unrelated locked job, an unrelated
inbox key, and non-execution of a proxy row's prototype trap. Genuine replay
remains idempotent. Content Control's own gate exercises substituted query
results with disposable PostgreSQL.

No provider account or live listing is exercised. No publication flag changes,
production SQL, or live Money Factory host checks are made. This is regression
evidence, not completion of marketplace or launch acceptance.
