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

Both POD HTTP handlers strictly decode the bounded raw body as UTF-8 before
JSON parsing. Invalid, overlong, surrogate or truncated byte sequences are
rejected instead of silently replaced before signature or scope checks. Valid
Unicode, including genuine replacement characters and multibyte sequences split
across transport chunks, is preserved without normalization. Leading byte-order
marks remain rejected, matching the previous JSON parser behavior. The event
handler returns its existing redacted 400 and performs no inbox connection; the
authority handler retains its redacted 409 and performs no snapshot lookup.
Size/time limits, signature verification, immutable event identity and grant
rules are unchanged. Local HTTP regressions cover these cases; live host mounting
and end-to-end acceptance still require separate verification.

Request-body deadlines also check elapsed monotonic time after decoding/parsing
and before business access. A body completing at or beyond the deadline cannot
start an inbox transaction or a snapshot lookup even if its timer callback was
delayed. The event endpoint returns 408 REQUEST_TIMEOUT; the authority retains
409 GRANT_BLOCKED for a completed late body. Existing timers still terminate
stalled streams. This cannot preempt synchronous work that blocks Node's event
loop; it prevents late completion from being accepted afterward. The authority's
five-second body and separate snapshot deadlines, and the event endpoint's
configured body timeout, are unchanged. Controlled-clock boundary tests are
unit evidence, not a measured production capacity or live timeout drill.

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

The review agent captures at most 4 MiB from a regular job file, strictly decodes
UTF-8 and requires a JSON object before invoking the child. Validation, rendering
and the receipt's `input_sha256` use that one captured byte version. The child
reads a private temporary snapshot, removed on success or child failure; changing
or deleting the caller's original path cannot change the rendered input or receipt.
Nonblocking open rejects FIFOs without waiting for a writer. This is input binding,
not an OS sandbox or protection from a malicious process running as the same user.
Existing output directories remain protected from overwrite.

After the child exits, result and manifest JSON are read only from regular files,
with strict UTF-8 and a 4 MiB ceiling each. Artifact hashes are streamed in at most
1 MiB chunks, with a 16 MiB per-artifact ceiling, at most 32 manifest entries and
a 64 MiB aggregate artifact ceiling, matching the downstream QA limits. Both
descriptor size and actual bytes read are checked so growth after stat cannot
bypass a limit. Nonblocking descriptor opens reject named pipes before reading.
The final receipt is created exclusively; an existing receipt file, symlink or
FIFO is never overwritten or opened for writing. Verification failure produces
no success receipt, and generated output remains available for investigation.
These bounds do not provide an OS sandbox, prevent same-user directory races,
or guarantee deadlines for stalled regular-file storage.

Nine output-verification regressions cover JSON/object/package limits, FIFO
results/manifests/artifacts/receipts, stale stat sizes, strict decoding, exact
ceilings and hash rejection. All 18 Python tests pass locally, including real
Node/Python review rendering using the prior pinned Content Control checkout.
The workflow now pins current CC 37949ade5137f1a6184f3bcf602e47eb7be7d3d4;
hosted cross-repository verification is required before merge. These tests do
not establish real rights, editorial approval, deployment or live acceptance.

Seven focused regressions cover mutation, deletion, child failure, size boundaries,
UTF-8/object validation and FIFO rejection. The real cross-repository test also
changes the original before Node/Python rendering and deletes it afterward,
requiring unchanged metadata, package hash and input receipt. Nine Python tests
pass locally against Content Control a033f8f2b3f411946ceb9fd1b93aaff75c5e73ca,
now pinned by the workflow. Synthetic review fixtures are not official templates,
rights evidence or live acceptance. Hosted results are recorded in Content Control's
POD_IMPLEMENTATION_STATUS.md; publication remains disabled.

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


## Sender storage cutoff and deduplicated recovery — October 17, 2026

Content Control PR #192 merged as c11f17968fea7d8e41d2d58d31c5762f917639ae. Its outbox
rechecks the existing 24-hour storage safety cutoff before each send and before
reporting batch completion, including empty pages. A cutoff is a batch-wide
rejection even when individual delivery errors are configured to continue. A
receiver may already have committed an in-flight event while the sender can no
longer commit its acknowledgement. Retain the stable event ID/content; do not
infer rejection from a missing acknowledgement or manufacture another event ID.

The cross-repository workflow pins that exact merged commit. Its PostgreSQL/HTTP
roundtrip now exercises the real sender storage and transaction gates: expire the
disposable sender after the first receiver commit, verify the second event was
not sent and both sender rows remain pending, then restore only the fixture's
expiry and retry both unchanged IDs. Each inbox event must exist exactly once.
Hosted verification is pending; local syntax validation is not database evidence.
The sender's own gate passed 372 Node and 157 POD Python tests, one durable E2E
and three workflow guards with zero failures/skips:
https://github.com/wecreates/content-control/actions/runs/39005696540

The previous MF pin passed 35 Node and two Python tests in
https://github.com/wecreates/Money-factory/actions/runs/38992242395
This new pin also includes cooperative task cancellation and exact-byte QA
snapshots; the MF roundtrip does not replace Content Control's full QA suite.
No production expiry is extended. Live authority mounting, retention, real grants
and all 24 acceptance areas remain open; both publication flags remain false.


## Idle database disconnect and delivery recovery — October 17, 2026

The cross-repository gate now pins Content Control b2b6799833eea5d2498458106e1069da6c34a97a. Its runtime pools handle idle-connection error events before connecting, retaining only a bounded incident count, timestamp and fixed diagnostic. The driver discards the failed idle client and a later acquisition can reconnect under the same TLS and timeout policy. Host-provided Money Factory pools also need an idle-error handler; this fixture does not configure or mount a live authority pool.

The existing PostgreSQL/HTTP roundtrip now attaches the real Content Control monitor, commits a sender event, terminates only its own disposable idle backend, and verifies removal before continuing delivery. The event must survive reconnection, a lost acknowledgement and unchanged-ID retry with one inbox row. The diagnostic remains recorded after recovery. Existing duplicate, expiry, cutoff and transaction rollback cases remain in the same gate. Local validation is syntax-only; hosted execution is pending.

Content Control PR #200 passed its full integration and production-image gates (401 Node tests, 157 Python tests and one durable E2E, zero failures/skips), including a separate actual PostgreSQL reconnection test:
https://github.com/wecreates/content-control/actions/runs/39020204979
https://github.com/wecreates/content-control/actions/runs/39020204915
This pin also includes cooperative independent-review cancellation and the stricter image startup probe. It does not establish production deployment, a live failover drill, current authority mounting or marketplace acceptance. All 24 live areas remain open and both publication flags remain false.


## Exact millisecond authority and inbox clocks — October 18, 2026

Grant issuance now requires nonnegative safe integer milliseconds for the
authority clock and approval expiry, matching Content Control's signed-envelope
contract. Invalid values cannot produce signed grants through either the direct
issuer or HTTP authority. The existing five-minute grant cap and approval/economics
expiry bounds remain unchanged. HTTP failures retain redacted 409 GRANT_BLOCKED.

The event inbox applies the same timestamp domain to signed event issuance and
to both clock reads: before acquiring a connection and after database waits,
before COMMIT. An invalid late clock rolls back without acknowledging delivery.
The existing inclusive five-minute event age and exact timestamp boundaries are
preserved. Retry the original event ID/content after recovery; these observations
never establish verified revenue.

Six of eight new contract regressions failed before repair; all eight and the
existing affected tests pass locally (59 Node tests total). HTTP regressions cover
invalid authority clocks. The hosted PostgreSQL roundtrip additionally changes
the fixture clock during a real unique-key wait, requires rollback and zero rows,
then retries the unchanged ID exactly once. Hosted execution is pending.

The cross-repository workflow pins Content Control
1d9f84c44eaa25454ff42843c232441e2633275c to verify this producer repair against its
current strict verifier and sender. Both publication flags stay false. No live
authority mounting, current approval, deployment, clock-health measurement or
24-area acceptance is claimed by these disposable tests. See Content Control's
POD_IMPLEMENTATION_STATUS.md for hosted results and remaining live evidence.


## Local generation retry recovery — October 18, 2026

The cross-repository workflow now pins Content Control f3dcddd9957378d92714616fdb1d7091fe79c3a6,
which removes its owned partial review directory when a Python generation stage
raises. The real MF → Node → Python test submits a forbidden worker-font override,
requires child failure and an absent output directory, corrects the brief and
retries the same destination. The retry must produce the original package hash,
REVIEW_REQUIRED result, publication false and matching Money Factory receipt.

This regression failed against the previous producer and passed locally against
the repair. Hosted verification is required before merge. Preexisting destinations
remain protected. Exceptions during downstream MF receipt verification still
preserve generated output for investigation; this change does not delete it.
Crashes, SIGKILL, default SIGTERM, denied cleanup and detected directory replacement
can still require manual recovery. Synthetic tests establish neither live recovery
nor authorizing approval; all production acceptance requirements remain open.


## Supervised local review CLI — October 18, 2026

Content Control a76d8cbf4c7ca8a316f24151f369ea346f97c0cb's pinned CLI now uses its existing Python-stage supervisor.
SIGTERM/SIGINT cancellation stops its POSIX process group, with a five-second
SIGKILL fallback, and cannot succeed merely because the child exits zero.
A successful parent exit with remaining process-group descendants also fails.
The four-minute deadline and disabled publication flags are retained; combined
output is bounded to 1 MiB and errors are reported without forwarding child stderr.

The cross-repository workflow runs the pinned CLI's seven subprocess regressions
alongside the existing Money Factory Node/PostgreSQL and Python bridge tests.
The actual MF → Node → Python generation/retry fixture passed locally against
this repair. Hosted exact-pin verification is required before merge; results are
recorded in Content Control's POD_IMPLEMENTATION_STATUS.md.

This is CLI lifecycle evidence, not a live authority or recovery drill. Abrupt
Node SIGKILL and escaped process groups are outside the guarantee, and default
Python SIGTERM can still leave partial output for manual recovery. It does not
add MF-parent signal forwarding or change Money Factory's timeout policy.
All live acceptance requirements remain open and both publication flags stay false.
