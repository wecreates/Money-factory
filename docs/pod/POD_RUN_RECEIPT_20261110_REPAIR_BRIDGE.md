# POD repair archive bridge verification

The isolated cross-repository workflow uses a current signed Money Factory
fixture grant and the pinned Content Control resolver, repair transaction,
and outbox with the existing Money Factory HTTP inbox. A revoked snapshot
must leave the failed row and archive untouched. After obtaining a new
fixture grant, one repair clears the old evidence from the active row while
retaining the exact archived attempt, manifest, QA evidence and reason. The
receiver records that exact archive. A second repair of the already queued
row must not create a duplicate.

The exact Content Control pin is `cb9cac085f619e1f23a32341691fb653351c75a4`.
Workflow results are tracked in the pull request. This does
not verify the live authority, the live database, marketplace adapters or a
production recovery drill. Both publication flags are off in the test, and
no live acceptance area is closed.
