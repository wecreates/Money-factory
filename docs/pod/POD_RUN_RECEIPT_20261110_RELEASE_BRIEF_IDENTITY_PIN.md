# Release admission verification

The bridge gate pins [Content Control PR 1166](https://github.com/wecreates/content-control/pull/1166)
and covers durable release admission in addition to the existing publisher
freshness checks. An inconsistent queue claim cannot submit or settle;
after a valid claim, the final guard rejects a changed brief or idempotency
key alongside the existing manifest and QA checks.

These tests use fixtures and disposable PostgreSQL only. They exercise no
provider, live Money Factory host, production database or publication
activation. They do not close live acceptance or verify continuous worker operation.
