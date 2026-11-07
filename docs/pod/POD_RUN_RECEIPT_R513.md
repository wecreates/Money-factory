# R513 — scope signed grants to the server-loaded job mode

Reconciled all 24 acceptance areas, current Content Control checklist, status and
free-deployment docs, open PRs, workflow results and authorized Render deployment.
Content Control main was 89a53122e533ab71bf9eb2d28ac8d474f754a0a3; concurrent
watchdog, QA and rollback-ledger changes were left untouched. Money Factory main
was 624a25bd913be68b30bdfc596eae32aa58055298. No duplicate POD PR was open.

## Reproduction and repair

Money Factory validated the business ceiling and dispatched launch-specific
approval, package, provider and economics checks only for a LAUNCH snapshot.
However, it signed the business ceiling and raw launch flags even for a narrower
job. Two baseline-failing cross-repository tests authenticated the actual issuer
output with the Content Control policy: a RESEARCH grant passed PRELAUNCH, and
a PRELAUNCH grant passed a LAUNCH brief for the same package with a broader
business ceiling. These were policy fixtures, not marketplace submissions.

The signed maximum is now the mode whose checks ran. Both launch flags are
false for RESEARCH and PRELAUNCH, including when the business has a broader
ceiling or its stored approval has publication permission. LAUNCH still requires
all existing explicit approvals, exact package, healthy providers and scoped
economics. The business ceiling still blocks a snapshot above its readiness
limit. Signed schema, audience, identity, expiry and sender pin are unchanged.
No existing signed token was retroactively revoked by this source change.

Focused issuer/consumer/economics suite: 18 passed. Full local Money Factory
Node: 289 passed and one expected disposable-PostgreSQL skip; Python: 81 passed.
Hosted exact-head verification and merge readback are in the implementation PR.

## Deployment and acceptance boundaries

Issuer-only repair. Content Control remains pinned at
cca116e003f7252210900ab862c3fb0ff9e87372 for compatibility testing. Both workflow
publication flags remain literal false. The existing free Render worker was
live on dep-dbn9h0p7m43s73bjq63g (89a5312, concurrent rollback-ledger revision);
no rollout was needed for Money Factory source. No authorized live Money Factory
issuer endpoint was available, so mounting, activation and real grant revocation
were not verified. The remaining 24 acceptance areas are still open. No changed
database-admin path or retry, paid resources, secret access, marketplace action
or external message. Scheduled tools do not establish an always-on worker.
