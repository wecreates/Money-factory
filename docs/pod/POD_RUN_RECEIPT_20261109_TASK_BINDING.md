# November 9, 2026 — retain production task scope when issuing POD grants

A Money Factory approval containing `task_sha256` was accepted even if the
server-loaded job omitted it. The signed result then had no task binding. The
new issuer and issuer/consumer regressions both failed on the original code.

Require a matching canonical SHA-256 digest if either the loaded job or the
approval specifies one. Absent on both sides remains valid for the existing
unscoped contract. A valid signed scoped grant is accepted for the exact job
task; the pinned Content Control consumer rejects substitution or removal.
Publication permission, the mode ceiling, revocation and expiry rules are
unchanged. This does not retroactively revoke previously issued tokens.

Consumer: [Content Control #1153](https://github.com/wecreates/content-control/pull/1153),
merged as `156931462d7ecc1d51798a936f7192e6884390b7`; its integration and container gates passed.
Local Money Factory Node: 293 passed, one expected disposable PostgreSQL skip;
Python: 81 passed.
The implementation PR records the exact hosted gate, Content Control pin and
merge readback. No authorized live authority was available to mount or verify.
No production DB administration, marketplace interaction, paid resource or
publication setting change. The 24-area live acceptance checklist remains open.
