# November 9, 2026 — verify the bounded recovery command in bridge CI

The Money Factory POD workflow pins the exact merged Content Control revision
from [the archive-session repair](https://github.com/wecreates/content-control/pull/1159).
Its existing boundary check now runs the archive lifecycle fixture alongside
the pinned transaction, deployment and restore tests. The test confirms a
standalone command cannot exit silently or report success while its owned pool
is stalled, and an already issued archive COMMIT is allowed to settle.

Both publication flags are literal false in this workflow. The fixture uses
no production database, keys or destination. It does not prove independent
retention, a production restore drill, or live Money Factory authority.
Hosted and merged-revision evidence is recorded on the associated PR.
All 24 live acceptance areas remain open.
