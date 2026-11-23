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
pair before using either file as a baseline. Writers must run serially, as the
hosted workflows do through their shared concurrency group. Never commit the
pending file. A fresh hosted runner cannot replay an interrupted runner's local
filesystem, and external readers that open both files outside the worker can
observe an in-flight write. Retained Git commits contain only completed pairs.

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
