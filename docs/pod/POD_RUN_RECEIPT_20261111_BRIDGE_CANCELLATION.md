# POD bridge native cancellation run — 2026-11-11 UTC

## Current source and selected repair

Fresh heads: Content Control `62e2d509e3320833eb5c7c999fa57e85068fea16`;
Money Factory `8e6a48310404a37f6138a8c9c26bad65e75ffd6b`. Both repository
trees had no AGENTS.md. No open POD repair PR duplicated this work; unrelated
video/social and Etsy changes were left untouched. The current completion,
implementation-status and free-deployment records were inspected. All 24 live
acceptance areas remain open.

The shared Content Control HTTP response helper accepted synthetic abort events
as real cancellation and read dependency-shadowable signal members during abort
checks and cleanup. Four new local regressions against the exact current helper
failed (0 passed, 4 failed): headers/body synthetic events ended an otherwise
pending request, and real cancellation read shadowed public members.

The repair captures native AbortSignal state/reason/check methods and EventTarget
listener operations. It ignores synthetic abort events without consuming the real
listener, removes listeners on completion, rejects forged/Proxy signals before
dispatch, and preserves real abort reasons. Existing monotonic deadlines, response
bounds, pending-header admission limits and late response cleanup are unchanged.
Seven legacy fake-signal fixtures now use genuine controllers or explicitly test
forged-signal rejection; no production caller needs a fake signal.

## Verification and limitations

Local affected tests: 139 passed, zero failed/skipped (bridge cancellation,
HTTP responses, grants and outbox suites). Six new regressions cover native
checks, Proxy rejection and both wait phases. Hosted candidate CI, exact merge
identity and Render rollout are recorded in the associated PR's verified-run
evidence after they are observed; this receipt does not preclaim their outcome.

The newest Full Capability Validation run 42976180517 had 12 passing scheduler
unit tests, then stopped with BLOCKED/selected 0/blocked capabilities 2500 for
missing capability metadata. Its validation job was skipped. This is a separate
fail-closed acceptance result, not a failed POD unit test; it was not suppressed.

At run start Render's existing free service srv-darsdb8u01pc73dn4i2g in workspace
tea-darsafojo6nc739844hg reported exact prior merge 62e2d509 live, deploy
dep-dbq08odg1s2s739av7ig, finished 2026-11-11T06:01:14.854722Z.
No new service, purchase, network change, credential, approval or database
administration attempt was made. Both publication flags remain false.
Money Factory's real authority host source is still absent from this repository
and its live mounting is unverified. Tests use local/disposable fixtures, not
production DB or marketplace acceptance. Free web hosting is not an always-on
worker guarantee. Current rights/accounts/adapters, retained independent recovery,
phone acceptance, measured capacity and controlled launch remain unverified.
No completion area is closed and the automation must not be disabled on this
repair's evidence alone.

## Content Control verified dependency

PR 1183 candidate bd9e6898fd165c25b0a009c7774f9df98a83a911 passed both
required POD gates and merged as 4659e4b885b4d4de2466a6f3059e10ab52656c46. This workflow pins that exact
merge and adds explicit shared bridge/header/body/grant regression coverage.
Money Factory candidate verification and rollout observations remain in its PR.
