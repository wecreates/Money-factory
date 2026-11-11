# Pinned release claim admission — November 10, 2026

The existing release-freshness suite now checks requested-account, destination,
platform and fencing consistency before any downstream callback. Only an exact
null adapter result establishes an idle queue.

The pinned workflow additionally runs the isolated real PostgreSQL claim test.
A restricted role claims a genuinely ready row with a conflicting destination;
the publisher leaves its acquired lease and quota reservation intact, makes no
authority/artifact/provider/settlement call and writes no new audit event.
Existing fenced recovery owns that state; no automatic retry is invented.

Only workflow-local disposable PostgreSQL is used. Test-only enabled function
inputs are not live flag changes or publication authority. No production
database, marketplace, clearance, independent QA or acceptance is verified.
All 24 live areas remain open. Exact hosted/merge/deployment evidence is in the PR.
