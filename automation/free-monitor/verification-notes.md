# Configured-watch verification

The verifier checks every configured active watch twice. Success requires a
nonempty active set, advancing timestamps, successful checks in both worker
reports, and matching healthy persisted state for the configured target URL. A two-cycle pass is not proof of
continuous monitoring, end-to-end production recovery, or a 24-hour agent soak.

When target checks fail after both files are persisted, the workflows keep the
new state and events and mark the run unhealthy. On unexpected execution or
persistence errors, verification and diagnostics can retain a separate failure
report. The GitHub workflows stage the two evidence files only after a completed
pair write. Worker and verifier exit status 2 denotes a completed but unhealthy
check; status 1 denotes an execution failure.

The worker syncs a pending file with both new JSON images before replacing the
state and events files. Restarting on the same filesystem replays the pending
pair before using either file as a baseline. On the same filesystem, the
worker holds nonblocking kernel `flock` locks on the canonical state/events
directories across replay, polling, reconciliation and persistence. Overlapping
workers sharing any of those directories fail before polling or changing the
pair. The lock is held by the worker's open descriptors, is released on
process exit, and creates no lock file. This requires util-linux `flock` and
filesystem support for directory locks. The hosted workflows still use their
shared concurrency group across separate runners. Never commit the pending
file. A fresh hosted runner cannot replay an interrupted runner's local
filesystem, and external readers that bypass the locked reader can observe an
in-flight write. Retained Git commits contain only completed pairs.

The scheduled worker restores and persists those completed pairs on the
dedicated `cyzor-free-monitor-state` branch. It must not commit cadence state to
`main`: doing so changed the repository page being watched, generated a false
repository-change event on the next cycle, and bypassed reviewed-PR history for
operational data. The repository watch now hashes GitHub's public `commits/main`
response, while the state branch changes independently. This prevents the
monitor from alerting on its own cadence writes. It does not make the monitor a
deployed alert-delivery service or establish 24-hour acceptance.

The manual/push diagnostic uses the same serialized branch. It restores the
last completed pair before probing, then writes its diagnostic report there. A
completed worker pair may advance state and events with that report; an
execution failure advances only the diagnostic and retains the prior completed
pair. Diagnostic evidence must never write to `main`. Commit `5b10b225` is the
retained hosted observation that exposed this second direct-write path after the
cadence fix. Moving it off `main` preserves the failure report without treating
operational evidence as reviewed source or triggering repository changes. This
branch design does not itself prove alert delivery, recovery, or a 24-hour soak.

The two-cycle verifier follows the same rule: restore the branch pair, write its
verification report there, and advance state/events only when the verifier
completed a pair. A failed verifier records the failure while retaining the
prior completed pair. Verification reports are operational evidence, not source
changes, and must not bypass reviewed `main` history.

## Durable invocation cadence evidence

The workflow declares `*/5`, but that declaration is not proof that GitHub
created an invocation every five minutes. The Actions run collection inspected
on November 24 shows scheduled run `45435294008` created and started at
2026-11-24T16:16:59Z. Its unit tests, worker and state-persistence steps all
succeeded; only the deliberate unhealthy-target gate failed. The previous
scheduled run was `45334172856` at 2026-11-24T05:33:41Z. Later worker runs at
16:43, 17:45, 18:42 and 19:15 UTC were push events, not scheduled events. The
18--57 minute durable-state gaps observed around those changes therefore do not
prove scheduled five-minute operation.

No scheduled-run records exist for the intervening expected ticks, and the
recorded scheduled runs started when they were created. That localizes the gap
before worker execution and state persistence; it does not identify why the
GitHub scheduler did not create each expected run. Platform scheduler telemetry
is unavailable, so the upstream reason remains unverified. Code cannot repair a
missing hosted scheduler invocation.

Each completed worker pair now retains a cadence receipt inside
`_monitor_runtime`. It records the built-in Actions invocation source and keeps
all-invocation liveness separate from scheduled continuity. Push, manual,
diagnostic and local runs can expose a durable gap but cannot advance scheduled
acceptance. Non-scheduled runs also fail the scheduled chain when the next
scheduled deadline is already overdue.

The operational worker reads the Actions event, run ID and attempt directly
from the process environment; callers cannot override worker options to relabel
a local invocation as scheduled. A qualifying run ID must be a positive decimal
GitHub ID and must increase strictly across every retained scheduled interval.

Scheduled receipts bind process starts to fixed five-minute UTC cron slots and
allow at most one minute of start drift from each slot. Continuity requires
adjacent slots, a new nonempty Actions run ID and attempt 1 for every retained
interval. Manual reruns and duplicate run IDs cannot advance unattended
acceptance, and per-run grace cannot accumulate into a slower false pass. Exact
gaps, overdue time and missed slots remain explicit. Missing, malformed, future,
internally inconsistent or discontinuous evidence resets continuity and keeps
the prerequisite false. A first scheduled observation is explicitly
insufficient. Only 288 consecutive scheduled intervals spanning 24 hours can
set `acceptance_window_verified` and `prerequisite_passed`; a single run, cron
declaration, successful HTTP response or local test cannot.

This receipt is detection evidence, not an alert consumer, a scheduler repair,
proof of a 24-hour soak, or proof that the monitored website recovered. It does
not change the workflow schedule or send or publish anything.

## November 21, 2026 investigation

At repository base `c73ca61d239c7f8e2dde3da60087a2c164695635`, the verifier still
looked for `cyzor-free-monitor-smoke`, absent from the current configuration.
The configured watches are `cyzor-website` and `money-factory-repository`.
`FREE_MONITOR_VERIFICATION.json` contains a pass dated October 7 for that old
smoke watch; it is historical evidence, not current verification.

Retained state reports a website timeout on November 21 at 5:00:11 PM Pacific
and a repository HTTP 200 at 5:00:32 PM Pacific. These are stored observations,
not fresh probes or evidence that the timeout is resolved. Local regression
fixtures exercise health failures, missing/stale checks, and configured watch
selection; they do not establish production uptime. Issue #543 remains the
single source of completion truth and retains actual-host/deployment blockers.

## Hosted observation after the fix

The retained report at commit `df8db63` was written November 21 at 6:40:08 PM
Pacific. Both current watches advanced through two checks. The website timed out
both times; the repository returned HTTP 200 both times. Overall `pass:false`
correctly replaced the historical smoke-test success. This is actual hosted
failure-retention evidence, not website recovery or a 24-hour soak.

That report also exposed a diagnostic coupling: per-watch health included the
whole cycle's `ok` value, incorrectly marking the repository's health false due
to the website failure. Per-watch health now describes that target's own check;
overall acceptance still requires both complete cycles to be healthy. The
original failed report remains historical evidence and is not rewritten locally.

## Response resource ceiling

The worker hashes decoded response chunks incrementally instead of buffering the
entire body. A response exceeding 2 MiB is cancelled and recorded as a failed
check; no partial digest replaces the previous successful hash and no change
event is emitted for overflow. The existing 20-second request timeout remains.
Chunked and compressed responses are bounded by decoded bytes, independent of
Content-Length. Successful worker results report `response_bytes` and
`response_limit_bytes`.

This bounds application-level response processing, not total process memory or
all resource use inside the HTTP stack. Overflow/recovery fixtures are local
technical evidence, not deployed overload/24-hour acceptance. The website timeout
remains a separate unresolved integration failure.

One ordinary workspace GET on November 21 at 7:50:19 PM Pacific also timed out
(curl exit 28; 20.000777 seconds; HTTP 000; zero response bytes). On that configured
network path, curl reported connection at 0.000128 seconds and TLS completion at
4.904375 seconds, but no first response byte. This narrows the local observation
to waiting after TLS; it does not locate the fault in the origin application,
reverse proxy or upstream. The normal workspace network may mediate DNS/connect
measurements. No retries, proxy overrides or settings changes were used. Actual
deployment/network logs remain needed to identify and safely resolve the cause.

## Configuration authority

Current watch configuration now controls normalized ID, target URL, kind, status
and label. Retained state supplies only observations from the same normalized
ID/URL/kind. Retargeting or changing kind clears the baseline, check/change times
and health before the new target is checked, preventing stale cadence from
suppressing that check and preventing a false content-change event between two
different targets. Pausing is respected; reactivation uses the normal cadence.

Local HTTP fixtures cover retargeting through the target_url alias, paused and
reactivated watches, label updates, unchanged history and kind resets. These are
regressions for configuration handling, not evidence of a production retarget,
website recovery or complete unattended operation. No configured target was
changed while implementing this behavior.

## Unique watch identity

The worker rejects duplicate normalized watch IDs before fetching targets or
writing state/events, including collisions between active and paused entries.
Previously, two targets sharing an ID could overwrite each other's state: a
later healthy target could hide an earlier failed target and make the overall
worker report healthy. Configuration must give each watch a distinct ID.

The regression is reproduced with isolated local fixtures; it is not an observed
production collision. The configured production watches already have distinct
IDs. Retained hosted state at `488cabef7d916a32e6efffa57fe0194a541d8857`
still records the website timeout at 2026-11-22T15:43:02.034Z and repository
HTTP 200 at 15:43:22.666Z. A separate public fetch on November 22 also timed out.
Neither this fix nor the repository response establishes website recovery,
self-serve onboarding, intended-host operation or 24-hour acceptance.

## Bounded retry evidence

Each due target now receives at most two attempts. A request keeps the existing
20-second per-attempt timeout; a retry waits 250 milliseconds and occurs only
for timeouts, fetch/network errors, HTTP 408/425/429, or HTTP 5xx. HTTP 4xx
responses outside that allowlist and response-size failures are not retried.
The worker validates hard ceilings of three attempts, 60 seconds per attempt,
and five seconds of configured base backoff even when called programmatically.

Every completed check retains its attempt count and per-attempt timing/outcome
in state and the worker report. A successful retry also records a
`retry_recovery` event; a target that exhausts its attempts remains unavailable
and retains each failure. An availability recovery still requires a later
successful check and is recorded separately. Local HTTP fixtures cover a first
attempt timeout followed by success, two exhausted timeouts, next-cycle
recovery, and a non-retryable 404.

This is bounded retry/recovery instrumentation, not evidence that the CYZOR
website recovered, that alerts were delivered, or that monitoring stayed live
for 24 hours. The public fetch path still timed out on November 24, 2026, and
deployment/network logs remain necessary to locate the origin of the delay.

## Pending alert outbox prerequisite

The worker now retains a strictly shaped `alert_intent` beside the state/event
pair when a target becomes unavailable. Repeated failures reuse the original
`unavailable_since` outage epoch and do not create duplicate pending work. If a
legacy retained outage has no alert intent, the next failed check backfills one.
Recovery retains both any missing outage intent and a separate recovery intent,
each explicitly marked `delivery_status: pending`, zero delivery attempts,
`external_delivery_performed: false`, and `publication_enabled: false`.

Pending intents share the existing crash-replay journal with state and events,
so an interrupted pair replacement replays before cadence decisions. Ordinary
change-event volume cannot evict pending delivery work: pending intents are
retained first and only the newest ordinary events fill the 500-event ceiling.
If pending work alone exceeds that ceiling, the worker fails before replacing
the retained pair rather than silently dropping an alert. Local adversarial
fixtures cover replay, legacy outage backfill, deduplication, forged delivered
records, recovery pairing, ordinary-event pressure and outbox overflow.

This is only a durable, bounded delivery prerequisite. It does not select or
contact an alert destination, send an external message, acknowledge delivery,
retry a delivery consumer, prove the hosted workflow is on cadence, prove
website recovery, or establish 24-hour acceptance. Those remain open C12
integration and runtime-evidence gaps. Publishing remains disabled.

The local alert consumer is a separate, explicitly non-external prerequisite.
It reads the exact pending intents, binds each record to a SHA-256 of the full
intent, and retains every bounded attempt in an atomic delivery ledger. A
strict local acknowledgement terminates one record; exhausting three attempts
retains a dead letter. Terminal records are idempotent, a reused event ID with
different content fails closed, and at most 20 intents run in one invocation.
The only built-in sink modes are `local-ack`, `local-fail-once`, and
`local-fail`; all retain
`external_delivery_performed:false` and `publication_enabled:false`. They are
for internal recovery/ledger verification and cannot satisfy external alert
delivery, acknowledgment by an operator, deployed operation, or a 24-hour
soak. The consumer serializes access with a nonblocking kernel `flock` held by
a pipe-bound helper; a live competing process fails closed, while a killed
parent closes the pipe and releases the kernel lock without stale-owner
deletion. The lock path can persist as an ordinary unlocked file. The consumer
rejects duplicate source IDs before acquiring that lock or invoking a sink. Its timeout
bounds how long it waits but cannot cancel a sink operation; any future real
adapter must be idempotent on the immutable intent ID and must reconcile an
ambiguous crash after an external effect. Running the consumer alone leaves
the producer outbox unchanged.

The serial worker may explicitly receive a trusted `localAlertLedgerPath`,
or `--local-alert-ledger <path>` when called from the command line.
It then moves exactly matched local acknowledged/dead-lettered intents from
the pending event queue to `_monitor_local_alert_archive` within the existing
journaled state/events pair. The archive stores the original intent and entire
attempt record. Current in-state archive rows remain in the ledger until a
verified rollover generation is committed. An interruption after event
replacement replays both images before the next worker uses them. Archived
outage identities prevent a continuing outage or subsequent recovery from
creating a second copy of that outage intent. A new recovery still queues
independently. Pending attempts and ambiguous duplicate outage/recovery keys
stay in the event queue. A full 500-record archive rolls its oldest 250
records into the bounded immutable generation chain before compacting a new
terminal intent. If the generation chain is full, compaction is deferred and
the as-yet unarchived intent remains pending.

The local worker and consumer accept regular ledger files up to 8 MiB and
1,000 records. After a generation is present in the committed paired state, a
later worker takes the same ledger lock as the consumer and removes only
structurally identical terminal ledger rows already retained in that verified
generation. Missing retired rows are idempotent. A disagreement fails closed
before polling or pair persistence. This keeps current and active delivery rows
within the ledger ceiling while the bounded generation chain retains older
attempt evidence and outage identities. The consumer rejects attempts to write
beyond either ceiling and leaves the previous ledger intact. Compaction
requires earlier attempts to all be errors and the terminal status, final
attempt, timestamps and last error to agree. Malformed terminal evidence leaves
the pending input in place.

The consumer also bounds its source events before taking the delivery lock or
attempting work: at most 8 MiB of JSON and 500 events, including unrelated
history entries. Sources must be regular files opened without following
symlinks and in nonblocking mode; named pipes fail rather than waiting for a
writer. Source and ledger reads use the opened descriptor and reject changes
in size, device, inode, nanosecond modification time or nanosecond change time.
Same-size in-place mutation therefore fails before delivery or compaction and
leaves the existing evidence artifacts unchanged. This bounds input loading
that the 20-intent processing batch alone could not bound. It does not establish
a total process memory quota or disk quota.

When the in-state archive reaches 500 records and another uniquely bound
terminal intent is ready, the worker retires the oldest 250 records to an
immutable hash-named generation beside the trusted ledger. The state keeps a
bounded, hash-chained manifest of at most 16 generations. Every later
reconciliation rereads each generation through a stable, no-follow bounded
descriptor and validates its digest, chain, records, IDs and outage keys before
deduplication. A crash after the generation is linked but before the paired
journal is installed reuses only the byte-identical generation on restart.
Generation exhaustion defers further compaction instead of evicting evidence.
Once a generation exists, later workers must continue to receive the same
trusted ledger path so they can locate and validate the retained chain; omitting
it fails closed before polling or rewriting state.

The archived local outcomes never stand for external delivery or operator
acknowledgment. The current hosted workflow does not supply a ledger, so
automatic deployed compaction is still unavailable. Local compaction and
rollover are not cadence repair or a 24-hour soak.

## Runtime resource observations and request envelope

Every completed worker pair now retains a fresh `_monitor_runtime` record beside
the watched targets. The record captures the current process CPU/RSS/heap
measurements; effective CPU and memory capacity from the host and cgroup-v2 when
available; filesystem total/free bytes; the exact active-watch count and retry
policy; and the bounded worst-case HTTP request envelope. Configuration is
rejected before any request when it exceeds four active watches or a 240-second
request envelope. The hosted job retains its separate five-minute wall timeout.
That wall value is recorded only when the three reviewed monitor workflows
explicitly declare the matching 300,000-millisecond context; direct/local runs
retain `null` rather than claiming a workflow limit they cannot establish.

The record deliberately separates observed finite host capacity from hard
per-process enforcement. Missing cgroup CPU or memory limits remain warnings.
Filesystem capacity is not represented as a process disk quota, so
`total_resource_ceiling_verified` remains false. This closes a hidden-evidence
gap and bounds the network portion of a run; it does not claim total CPU/RAM/disk
enforcement, restored cadence, alert delivery, website recovery, or a 24-hour
soak. Those remain C12 acceptance blockers. Publishing and external delivery
remain false.

The monitor persistence reader applies an 8 MiB ceiling to each state, events,
and pending-journal input. After validating an ordinary state/events pair, it
also measures the exact pretty-printed pending journal and rejects a combined
snapshot over 8 MiB before any watch request. Reads reject non-regular files,
oversize files, and descriptor metadata changes in size, device, inode,
nanosecond mtime or nanosecond ctime. The no-follow/nonblocking descriptor flags
are currently Linux-compatible; a platform without those flags fails closed.

This bounds persisted input loading and prevents a pre-existing pair that
cannot fit its recovery journal from reaching network work. The writer still
uses the ordinary JSON serializer and does not claim a bounded serialization
allocation or a total output/disk ceiling. A newly generated state/events pair
is now serialized once as its exact recovery-journal image before any pending
or temporary artifact is created. That image is parsed into ordinary JSON
values, and the exact materialized values produce both legacy files. A nested
`toJSON` hook therefore cannot return a small preflight image and a larger
write image. An image above 8 MiB leaves the existing pair byte-identical.
The paired writer now gives each destination a path-derived temporary-file
prefix. After obtaining every pair-directory lock, a worker removes only
single-link regular temporary files attributable to the state, events or
pending destination. A matching symlink, directory or multiply linked file
fails closed. This recovers crash leftovers without touching concurrent ledger
or unrelated atomic output. Unrelated files, retained archive generations and
other atomic JSON outputs can still consume disk, so
`total_resource_ceiling_verified` remains false.

Offline inspection on 2026-11-25 found the checked-in state at 905 bytes and
events at 65,458 bytes. Their exact recovery-journal image is 70,559 bytes, so
all three current artifacts are below the 8,388,608-byte input ceiling.

## Linux bounded-process supervisor prerequisite

The optional local resource supervisor now runs a requested executable through
Linux `prlimit` with per-process CPU-time, address-space and single-file
ceilings. Descendants inherit those limits, but CPU time and address space are
not aggregate tree-wide CPU or RAM quotas. The supervisor measures its direct
process from `/proc` and watches the complete declared output directory,
killing the process group when aggregate retained bytes exceed the declared
total. An independent wall timer kills the process group at the declared wall
deadline. The supervisor repeats aggregate-output and wall validation after
process exit so a fast writer cannot finish successfully between polls. The
output walk rejects symbolic links, special files and more than 10,000 entries
instead of following data outside the bounded root. A missing child caused by
an atomic rename/delete between directory enumeration and metadata inspection
retries the complete snapshot at most four times; persistent disappearance and
all non-missing-path errors still fail closed. Every receipt explicitly leaves
total-tree CPU and memory quotas false and keeps publication, paid inference
and external delivery false.

The test suite exercises the real monitor worker inside those limits, then
uses real CPU pressure, memory pressure and multi-file disk workloads to prove
the three enforcement paths. This is a Linux local-execution prerequisite. It
does not change the hosted workflows, prove their deployed limits, establish a
host-wide or aggregate process-tree CPU/RAM quota, or close C12.04 without an
authorized deployed workload and its retained receipt.
