# Configured-watch verification

The verifier checks every configured active watch twice. Success requires a
nonempty active set, advancing timestamps, successful checks in both worker
reports, and matching healthy persisted state for the configured target URL. A two-cycle pass is not proof of
continuous monitoring, end-to-end production recovery, or a 24-hour agent soak.

The verification workflow persists state, events and the report even when target
checks fail, then marks the job failed. Exceptions replace a stale report with a
new failed report rather than retaining an old pass. It keeps the existing watch targets,
schedule and disabled content-publishing settings unchanged.

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
