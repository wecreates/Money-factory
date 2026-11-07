# R512 — bound Money Factory inbox client cleanup before acknowledgement

Reviewed all 24 acceptance criteria, current implementation/free-deployment docs,
open PRs and POD workflows in both repositories. Content Control main was
791dd76021d060163e7cbac627bae26783824bf9; its concurrent health-only commit is
untouched. Money Factory main was 463691beea1707312e86f8b989bc8f410efb5db0. No
duplicate POD PR or job was open. Prior hosted POD gates were green.

## Reproduction and repair

The receiver did not await asynchronous PostgreSQL-client release. Three focused
regressions failed against baseline: it acknowledged a committed event while
release was still pending, and also acknowledged after rejection or stall.

Release now starts exactly once, even when the transaction budget has expired.
Verified native Promise cleanup must complete within the same monotonic
transaction deadline before a success is returned. A rejected or unverifiable
release after COMMIT withholds acknowledgement and returns the existing redacted
503. The row may already be committed: retry the exact event via the existing
ID/hash deduplication path, not a compensating rollback or a second release.
An earlier transaction failure is preserved. Rejections from late unused-client
release are consumed without delaying the connection timeout. Arbitrary
thenables are not invoked. A timeout does not prove underlying I/O was canceled.

Local tests: 287 Node passed, one expected disposable-PostgreSQL skip, zero
failures (288 total); 81 Python tests passed. The eight added cases cover deferred
success, reject/stall, monotonic completion, thenable rejection, primary error
preservation, redacted HTTP rejection and late cleanup. Hosted cross-repository
verification and merge readback are recorded in the implementation PR.

## Deployment and acceptance limits

Money Factory-only receiver repair. The existing Content Control consumer pin
remains cca116e003f7252210900ab862c3fb0ff9e87372 and both workflow publication
flags remain literal false. Authorized free Render service remains live on
dep-dbn8bcks728c73901070, the same exact Content Control revision. Do not trigger
a duplicate rollout or treat its liveness as Money Factory receiver deployment.
No separately authorized live Money Factory inbox endpoint was available to test.

All 24 live acceptance areas remain open. No new database-admin path was found;
no retry, production activation, live database mutation, paid resource, rights
claim, secret access or external message. The scheduled environment is not proof
of a continuous self-hosted worker. The completion condition remains unmet.
