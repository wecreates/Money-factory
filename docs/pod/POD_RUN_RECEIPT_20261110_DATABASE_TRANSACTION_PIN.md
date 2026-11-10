# November 10, 2026 UTC — database transaction boundary pin

Pin Content Control main at `c7f909e2048d175f7d1fcc140ff0335f94d19f24`, the exact
merge of [POD database transaction verification](https://github.com/wecreates/content-control/pull/1157).
The Content Control integration and container gates passed before merge.
The existing Money Factory workflow adds the pinned consumer's deployment and
migration fixtures to its transaction step; both publication flags stay false.

Local verification: 300 Money Factory cases passed (one expected PostgreSQL
skip); the expanded consumer step passed 97 cases (two expected PostgreSQL
skips). Content Control runs its real database fault fixtures separately;
Money Factory retains its isolated grant and outbox round trip. Hosted CI
and merge evidence are recorded in this pin's PR.

This changes CI, not the live Money Factory authority. No production migration,
database retry, backup, publication, or marketplace operation was performed.
All 24 live acceptance areas remain open.
