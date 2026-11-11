# Grant request cancellation — 2026-11-11 UTC
Fresh CC head 8d57f4c7b9d7bdd1399b701d37a4a078e60ead73 and MF head
32e03c47442e16844053c7cd9169ce448ce2633a were read before changes.
The MF monitor-only concurrent commit modified FREE_MONITOR_EVENTS.json and
FREE_MONITOR_STATE.json; it is preserved. No AGENTS.md or duplicate POD PR
was present. Current checklist, active status and free deployment records were
inspected. All 24 live acceptance areas remain OPEN.

The exact current grant client and tests were fetched before reproduction.
Its per-call destructuring invoked a signal accessor before validation.
Local regression run: 21 tests, 20 passed, one new accessor rejection case
failed with the getter's error. Five new cancellation cases passed locally on
Node 24 but also guard the Node 22 composition boundary exposed in prior #1184.
No Node 22 red result is claimed for this change.

Use data-only cancellation capability lookup and captured native signal
state/reason/listener methods. Requests compose their timeout with an owned
signal, never the caller's shadowable public members. Synthetic events do not
consume genuine cancellation; cleanup removes the relay on all outcomes.
Six cases cover executable options, forged/Proxy signals, already-cancelled
reason, valid grants with shadowed members, and header/body waits. Scope,
signature, expiry, revocation, byte/deadline and publication checks remain.

At start existing free Render service srv-darsdb8u01pc73dn4i2g in workspace
tea-darsafojo6nc739844hg reported 8d57f4c live through deployment
dep-dbq23sl9el5s73932ffg. Required hosted candidate gates, merge identities,
dependent MF pin and rollout observations are recorded in the associated PRs.
Local tests are not full current-source or production acceptance; hosted exact
candidate verification is required before merge.

No credentials, production SQL, marketplace call, network/service setting change,
paid resource, fabricated approval or social-vault access was used. No credible
changed DB administration path exists, so it was not retried. MF authority
mounting, independent retained recovery, current owner-authorized accounts,
sources/rights/templates/adapters, independent QA, phone acceptance, actual
finance and measured 100/1,000 concepts/day remain unverified. Both publication
flags stay false. No continuously running self-hosted worker is claimed.

CC #1185 passed both required POD gates and merged as a2d9e5b49d40ebd715c554ac1b7ba0109adfd4bb.
MF pins that exact merge; its existing explicit grant suite includes all six new cases.
