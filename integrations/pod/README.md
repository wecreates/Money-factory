# Content Control POD bridge

`readiness-grant.mjs` reads the existing CONTENT_READINESS.json object supplied by
the authoritative MF process, requires a scoped approval backed by an upstream
event, and signs a short-lived grant. It never changes a business max_mode.
Invoke with server-loaded data only; do not accept caller-supplied readiness or
approval objects at a public route.

`event-inbox.mjs` verifies Content Control event signatures and transactionally
deduplicates delivery. Apply `001_event_inbox.sql` through the existing migration
owner, then bind acceptPodEvent to an authenticated internal POST endpoint. This
module is not yet mounted in the deployed MF core: its runtime source is not in
this repository root. Downstream observations do not count as verified profit.

`event-handler.mjs` supplies the matching Node HTTP transport. Mount
`createPodEventHandler({pool, key: POD_OUTBOX_KEY})` on the existing internal HTTPS
authority host after applying the inbox migration through its migration owner.
The key must match Content Control's dedicated outbox key and must not be reused
as a grant-signing or reviewer key. Preserve the raw request stream; mount before
any middleware that consumes JSON. This handler authenticates the signed envelope,
requires its event ID to match the Idempotency-Key header, limits request size and
read time, and acknowledges only committed events. Re-delivery of the same event
is safe; conflicting content returns 409. Database failure returns a redacted 503
and remains retryable. It never updates readiness or the verified revenue ledger.
Tests use an in-memory transaction double and a real local HTTP server; they are
not evidence that the deployed authority or production database is configured.

Tests: `node --test integrations/pod/readiness-grant.test.mjs`.
Content Control tracks all 24 live acceptance areas in POD_COMPLETION_CHECKLIST.md
and implementation/test evidence in POD_IMPLEMENTATION_STATUS.md. Publishing stays disabled. Etsy pipelines are
outside this lane; their independent workflows are preserved.

Production-only approvals may now set `production_permission: true` and
`publication_permission: false`. Scope, expiry, evidence event and readiness
checks still apply. These grants authorize internal RESEARCH/PRELAUNCH work only;
LAUNCH requires explicit publication permission, healthy providers, launch
readiness and a bound package hash. The matching Content Control policy must be
deployed before using production-only grants. No grant adapter is mounted in a
live Money Factory service by this change.

## Python review production agent

Run a supplied review brief through the existing Content Control checkout:

```sh
python3 integrations/pod/production_agent.py --job reviewed-job.json \
  --content-control /path/to/content-control \
  --font /path/to/licensed-font.ttf --output /new/review-output
```

The job requires `publication_enabled: false`, `paid_generation_enabled: false`,
`platform`, `metadata`, `original_art`, `cover_template`, and for KDP an `interior`
containing a template and actual manuscript pages. `market_research` observations
are preserved as unassessed input, not invented market evidence. The test fixture
in `test_production_agent.py` demonstrates the schema with synthetic dimensions;
it must not be published as a product. Font selection belongs to the worker.

The agent invokes Content Control's Node coordinator and Python production modules,
checks the full manifest and each artifact, then writes a receipt. It creates real
art and PDFs, but deliberately reports REVIEW_REQUIRED. It does not provide a
live authorizing service, verified marketplace data, paid generation or publishing.

Cross-repository test:
`CONTENT_CONTROL_ROOT=/path/to/content-control python3 -m unittest discover -s integrations/pod -p 'test_*.py'`.

Durable production inputs are now bound using `job.task_sha256`. When present,
the authoritative approval must contain the identical task_sha256 before a grant
can be issued. This prevents a client changing stored production inputs after
approval. Content Control resolves that descriptor from its existing ArtifactStore,
persists generated files, then waits for package-bound QA; it does not invent an
approval just because production completed.


## Official-template scope in durable production tasks

Content Control PR #70 now enforces official-template provenance in its production
worker before invoking any Python stage. A stored task descriptor must include
`templateScope: {product, country}`, with a nonempty product identifier (at most
128 characters) and an uppercase two-letter target country. The platform comes
from the authorized job. The template authority's signed cover record must match
that exact product/country/platform, identify its verified official source and
source SHA-256, and have a non-future observation time. KDP interiors require a
separate `pod:interior-template` record with the same scope, checked before cover
generation. Current signatures alone are not a substitute for official provenance.

This is bound through the existing `task_sha256` approval/grant contract above;
there is no new caller-supplied readiness or approval field. Legacy descriptors
without scope fail closed. Build a new immutable descriptor from actual approved
inputs and obtain a fresh authoritative approval for its new hash. Never infer a
country/product, modify content-addressed bytes or invent official-source evidence.

The standalone review agent remains a review-only tool; synthetic rendering
specifications do not satisfy this production gate. Publication stays disabled,
and live authority mounting, template validation and marketplace acceptance remain
unverified. The repair's disposable PostgreSQL/Python gate passed:
https://github.com/wecreates/content-control/actions/runs/38599545277

## Durable market evidence and current local release eligibility

Content Control PR #76 requires stored immutable evidence for incoming market
observations. Source proof is mandatory; image and rank proof are required when
claimed. Rank proof is retained by migration 003. The signed market envelope is
still issued by the market authority, not by this readiness-grant module.
Exact source/platform/observation-time retries return the original record ID;
conflicting country, category, price/currency, rank, hashes or observation JSON
are rejected. Do not refresh timestamps or fabricate proof to force a conflict
through. Old rows without retained rank proof are not retroactively verified.
The detailed contract is integrations/pod/MARKET_EVIDENCE.md in Content Control.

The review agent's market_research field remains unassessed input. Inclusion in
a brief, a signed grant or an immutable artifact does not establish current
demand, permitted collection, trademark clearance, unit economics or profit.
The market repair passed its disposable PostgreSQL/Python gate before merge:
https://github.com/wecreates/content-control/actions/runs/38622442650
Production requires separately verified deployment and checksum-managed migration;
neither was established by that test. Existing publication flags remain false.

Content Control's release executor additionally requires current local job lease,
fencing token, account state and non-tombstoned rights after remote grant lookup.
A valid Money Factory grant cannot override those local denials. Grant/QA expiry
is rechecked after the final database wait. Do not renew an upstream grant to
revive an expired claim, suspended account or permanently blocked concept.
This is not atomic cross-system revocation; authorized adapters still require
provider idempotency and observed-result reconciliation. No real adapter or
live authority mounting is supplied by these code changes.

## Financial line identity

Content Control's financial intake requires a one-to-one match between the
provider event and `authority_event_id`. A new provider/event ID cannot count an
existing upstream financial event again. An exact retry must preserve job,
provider, provider-event ID, kind, amount, currency, occurrence time, proof hash
and authority ID. It returns the original row without another outbox event.

Provide actual verified line-level upstream events for compound statements.
Do not reuse one statement-level authority event for many imported lines, derive
new authority IDs locally, or refresh occurrence times to bypass a conflict.
Future-dated forecasts are not financial occurrences. Migration 004 fails closed
if existing rows reuse authority IDs; it does not delete or relabel history.
Existing ledger reconciliation/approval is required for any historical conflict.
The matching contract is Content Control's integrations/pod/FINANCIAL_EVIDENCE.md.

This rule does not mount a live finance authority, confirm any provider statement
or turn downstream net-recorded amounts into verified profit. Money Factory's
inbox remains observation-only; its verified revenue ledger remains authoritative.
Production migration/deployment and all real financial acceptance remain separate
from disposable CI. Publication stays disabled.


## Production lease and QA freshness at readiness — October 15, 2026

Content Control PR #92 checks production leases using wall time after acquiring
row locks. Late failure, review-hold and completion writes are rejected, including
a worker whose fencing token still matches. An upstream grant cannot revive that
lease. PR #93 additionally revalidates signed QA after connection and rights-row
waits, immediately before accepting a review or completing production. An expired
review cannot create readiness or a readiness event. Obtain a new independent
review of the exact package; do not rewrite or extend a stale signed envelope.

The existing Money Factory bridge fields, readiness ceiling and grant/event
contracts are unchanged. The current Content Control migration set is 001–005;
matching checksums and the restricted runtime role must pass production preflight.
An expired lease is a recovery incident, not a reason to relax local release checks.

PR #92 merged as fb3cf86e0cde856aba6f2d2dcfd3c7999610ebb4 after CI run
https://github.com/wecreates/content-control/actions/runs/38692725008 passed.
PR #93 merged as 9e453ab3b3a35650b259b6bad1da5d42b63b1108 after CI run
https://github.com/wecreates/content-control/actions/runs/38693182715 passed
(162 Node tests with zero skips, 42 POD Python tests and the durable PostgreSQL/Python
review workflow). Lock-barrier fixtures and synthetic signatures are test evidence,
not live marketplace acceptance or independent legal/quality clearance.

Render's deployment of PR #92 explicitly failed for exhausted build minutes.
The PR #93 deployment dep-db878hh42hec73bvr330 also reports build_failed at
2026-10-15T06:35:51.903655Z. Neither repair is verified deployed. Live authority
mounting, production migration/access and all 24 acceptance gates remain open.
PUBLICATION_ENABLED and POD_PUBLICATION_ENABLED remain false; this checkpoint
creates no grant, release authorization, revenue event or continuous worker.

## Inbox freshness through database waits — October 15, 2026

The receiver now reevaluates its five-minute event-envelope window immediately
before commit, after insertion and replay comparison. An envelope that ages out
during connection or uniqueness waits is rolled back and not acknowledged.
The HTTP sender must retry with a current envelope for the same immutable event;
it must not change the event ID/content or infer delivery from a missing response.
The receiver still records observations only and cannot promote verified profit.

The internal acceptPodEvent fourth argument is now a clock function, defaulting
to Date.now, instead of a captured numeric timestamp. createPodEventHandler passes
its existing clock function through. Use a callable clock for deterministic tests;
numeric callbacks fail closed, and nonfinite clock readings reject the event.
The external HTTP envelope, Idempotency-Key header and acknowledgement schema
are unchanged. No source timestamp or signature is rewritten by the receiver.

Two local HTTP regressions reproduced the late acknowledgement and missing clock
configuration check before the fix. All seven HTTP tests now pass. The hosted
PostgreSQL roundtrip test adds a unique-key contention barrier and verifies that
an event expiring while blocked leaves no inbox row or acknowledgement. Hosted
verification is required before merge; this does not mount a live MF authority.

Related Content Control PR #95 (b541c3c45f4968dd1647989fb52c0587399f4f9b) rejects
expired intake/queue grants and locks rights during repair; PR #96
(790e32805d66caf8de360e3b796f1075d3866d6a) rolls back evidence/QA that expires during
final database writes. Their gates passed respectively:
https://github.com/wecreates/content-control/actions/runs/38694726760
https://github.com/wecreates/content-control/actions/runs/38695345427
The latter passed 194 Node tests with zero skips, 42 POD Python tests and the durable
PostgreSQL/Python workflow. Merged-main integration and wiring also passed.
Render still reports failed deployment attempts; live acceptance remains unverified.
Both publication flags stay false. No credentials, permissions or ledger facts change.


## Current economics required for LAUNCH

The server-owned snapshot now supplies the version-1 price/economics contract in
RELEASE_ECONOMICS.md. LAUNCH signing requires current complete evidence, exact job/
account/business/platform/package scope, and approval.economics_event_id matching
the economic decision. Grant validity is capped at the economics expiry. The HTTP
endpoint still accepts only job_id; clients cannot inject prices or cost approvals.
Production-only PRELAUNCH does not require or manufacture a release budget.

The counterpart is Content Control PR #123. Its exact implementation commit
721f475c95d6a7cd84f5d0da9199c09f90ffebdc is pinned in the cross-repository workflow so the
signed-budget roundtrip uses the actual downstream release validator. Six shared
numeric/scope/expiry test vectors, two issuer tests and the roundtrip were added.
17 focused local MF tests passed, alongside 42 local CC tests; hosted execution and
merge verification are pending. No live cost source, approval, financial event,
publication switch or database configuration was created. Actual economics and
all live acceptance requirements remain unverified.

## Inbox database failure recovery — October 16, 2026

Every inbox transaction now sets a two-second lock timeout and ten-second
statement timeout before writing. Server-side cancellation rolls back the
transaction and sends no acknowledgement; the existing HTTP handler returns a
redacted retryable 503. A failed rollback discards the connection from the pool
instead of reusing unknown transaction state, while preserving the original
failure. Successful rollback and commit return healthy connections normally.

These deadlines apply to PostgreSQL locks and individual statements, not to pool
acquisition or a broken network. The authoritative host must supply a bounded
pool with connection/query deadlines and verified TLS. No new live pool, database
role, credential, ingress route or readiness permission is created here.

Three focused regression cases failed before repair; eleven local transaction/
HTTP tests pass afterward. The PostgreSQL roundtrip fixture now holds an exclusive
lock and independently runs an intentionally slow test trigger, checks SQLSTATE
55P03/57014 respectively, verifies no row survived, and retries the same event IDs
successfully. Fault injection checks failed-rollback disposal. Hosted verification
is pending; synthetic tests do not establish deployment or live delivery.

The cross-repository workflow pins Content Control's verified main commit
53b39bc685705ff1743a70b08f1ebdae707c94de so the receiver is exercised with the current
sender and review production modules. Both publication flags stay false. All 24
live acceptance areas remain open in Content Control's completion checklist.

## Bounded authority snapshot lookup — October 16, 2026

`createPodAuthorityHandler` now passes an AbortSignal as the second argument to
`loadSnapshot(jobId, {signal})`. Its `snapshotTimeoutMs` defaults to 5,000 ms and
must be an integer from 1 through 10,000. This is separate from the existing
five-second request-body read deadline. A timeout or client disconnect aborts the
lookup signal; the handler discards late results and never signs them. Elapsed
monotonic time is checked after resolution, so delaying a timer callback does not
extend the deadline. Blocked connected requests receive the existing redacted
409 GRANT_BLOCKED response. Non-callable or nonfinite authority clocks fail closed.

The host's loader must honor cancellation and use bounded pool acquisition,
database query and network deadlines. The handler cannot forcibly cancel an
arbitrary loader or preempt synchronous work that blocks Node's event loop. It
does prevent such late results from becoming grants. Existing one-argument loaders
remain compatible but must implement cancellation before live capacity acceptance.
No authority host, current approval snapshot, credential or production grant is
created by this change. There is no fallback to an old queue approval.

Four regressions failed against the old handler, and a further delayed-timer
regression failed before the monotonic check. All 22 focused local authority,
readiness and economics tests pass. The cross-repository workflow now pins tested
Content Control main 876cb6217ef41bd6690070b8090d261b0de390fd. Hosted verification and
merge evidence are pending. Both publication flags remain false and all 24 live
acceptance areas remain open in Content Control's registry.


## Cross-repository credential isolation checkpoint — October 17, 2026

Content Control PR #186 merged as ec034eae057206120a8b2d0b14c0e62412dc032a after its
PostgreSQL/Python gate passed 361 Node tests, 148 POD Python tests, one durable
end-to-end test and three workflow guard tests, with no failures or skips:
https://github.com/wecreates/content-control/actions/runs/38992101973
Its startup and read-only preflight now reject reuse across all configured POD
evidence and transport credentials, including grant authentication and outbox.
Keep those transport keys distinct from grant signing, independent QA and all
other evidence authorities. Absent optional lanes remain disabled; no credential
is generated, rotated, disclosed or configured by this checkpoint. The matching
contract is Content Control's integrations/pod/KEY_ISOLATION.md.

The cross-repository workflow now pins that exact merged Content Control commit,
so grant/receiver and review-production compatibility are tested against the new
runtime tree rather than the previous pin. Hosted execution of this pin is pending.
The earlier bounded-lookup change in MF PR #23 passed 35 Node and two Python tests
in https://github.com/wecreates/Money-factory/actions/runs/38989886466 and merged as
74af2af36dbbc75a377abfa2595c7ee378925a2e; its source tree matched the tested tree.

This is implementation and disposable test evidence. The authoritative host and
current snapshot loader still need live mounting and verification; independent
credential custody and rotation are not established by checking configuration.
Render still serves an older Content Control commit and its build-minute blocker
remains unresolved. All 24 live acceptance areas remain open. Both publication
flags remain false. No marketplace publication or verified revenue is claimed.
