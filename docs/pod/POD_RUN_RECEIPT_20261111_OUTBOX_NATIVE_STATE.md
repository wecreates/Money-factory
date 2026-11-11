# Direct outbox native cancellation — 2026-11-11 UTC
Fresh heads: CC 4659e4b885b4d4de2466a6f3059e10ab52656c46 and MF
f211e16c0e8e4fce5b8242c0daaca44a17092523. No AGENTS.md or duplicate
open POD repair was present. Current checklist, active status and free deployment
records remain unchanged; all 24 live acceptance areas remain open.

The exact remote outbox source was refreshed before reproduction (local older
source was not used as current evidence). Three red regressions showed native
abort hidden by a false public flag: storage was reached and failures increased
at entry/after selection. An executable public aborted getter was also invoked.
Captured native state now controls entry, row, error and final-storage checks.
Forged/Proxy signals are rejected before storage without invoking public members.
Original signal identity still reaches database reads/transactions. AbortSignal.any
retains native composition. A committed delivery stays counted after cancellation;
an aborted fetch never writes its delivery marker.

Eight new cases cover entry, selection, getters, forged/Proxy signals, normal
delivery, fetch abort and commit-boundary abort. Hosted exact-candidate checks,
merge and rollout evidence are appended to the associated PRs when observed.

At start Render's existing free Docker service srv-darsdb8u01pc73dn4i2g,
workspace tea-darsafojo6nc739844hg, reported prior exact merge 4659e4b live
via dep-dbq1ck5g1s2s739c797g. No service/env/network change, paid resource,
production SQL, credential or marketplace call was made. No credible changed
database administration path exists, so it was not retried. MF live authority
mounting remains unverified and its host source absent from this repo.
Tests/disposable databases do not close production acceptance. Independent retained
recovery, current owner-authorized accounts/rights/templates/adapters, phone
acceptance and measured 100/1,000 concepts/day remain unfinished. Publication
flags stay false; no continuously running self-hosted worker is claimed.

Initial hosted candidate 01e01792053b401a40c5af75fd00bd757a855c18 failed
integration run 42983199225: three delivery regressions exposed Node 22's public
aborted read during AbortSignal.any composition (local Node 24 did not read it).
The repaired candidate composes request deadlines from an owned native-state
mirror and removes its source listener in finally. The original signal is still
passed to database I/O. Superseded CI is not counted as acceptance.

CC #1184 passed both required POD gates and merged as 8d57f4c7b9d7bdd1399b701d37a4a078e60ead73.
The MF workflow pins that exact merge and adds the eight native-state cases.
