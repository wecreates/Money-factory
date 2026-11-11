# Reuse verified installed CI fonts — November 11, 2026

Resumed CC #1191 at c5ffb5f48f3e220859e79d8aaabe78e70f973c5f and MF #519
at ffbbb3b005df380250aae26521ce1f5ad317a927. Their prior pending MF run
43062512310/job130668576715 was canceled after about20 minutes in apt update
(16:52:50Z–17:12:35Z), before any contracts ran. It is not a passing run.
Earlier MF logs verified fonts-dejavu-core was already installed. Repeatedly
updating repository metadata before checking installed dependencies wasted the
free runner's budget. No unchanged retry or CC DNS retry was dispatched.

The MF job now checks all12 expected DejaVu Sans/Mono/Serif faces at their fixed
system paths, opens each with Pillow, verifies its family and rasterizes sample
text to a nonempty mask. Success reuses the installed dependency without apt.
If any required face is missing, wrong-family, unreadable or non-rendering,
the same configured apt repositories install the same fonts-dejavu-core package
within120 seconds plus up to5 seconds forced termination. Post-install font
validation is mandatory. Errors/timeouts remain failing gates. No substitute
font, ignored failure, widened network/DNS/mirror setting or test skip.

Nine offline tests pass locally: all exact faces checked; missing, wrong-family
and non-rendering faces rejected; installed-font path performs no package calls;
missing fonts install then recheck; install failure propagates; stalled update
expires; failed post-install verification rejects success. Fixture timeout is
scaled to0.5 seconds, not claimed as production timing. Bash syntax passes.
Actual local Pillow rasterization and the full shell existing-font path pass,
printing POD_CI_FONTS_VERIFIED_EXISTING. Hosted results must be recorded in #519.
New tests join the existing MF aggregate Python suite, without duplicate runs.

Current main advanced independently: CC bc9c08386c6369990cb5a8d44369dd2069ab431e
changed only3 video QA/ledger report files; MF9f8151dd467dfc8518818b7aaf9953361fc032aa
changed only2 free-monitor state files. Preserve both. MF candidate incorporates
its two concurrent monitor files without editing their bytes. No repository
AGENTS.md found. Checklist/free-deployment GitHub blobs remain580f8027d946fc34d4ecc28b208652f01ca5e4ac
and e4f64cc489bb4fdbc2a1e1f235f2b29507fd7676; current contents read. Status blob
ee5017b86f4b13f8d597c43b4ab09ee3f21ca6db was verified against the retained local
copy before reading its active status; fetching the entire1MiB file was rejected
by the connector. Initial local execution attempted an obsolete scratch path;
using the current workspace succeeded. No missing-path attempt counts as a test.

Read-only Render metadata reports existing free Docker service in the authorized
workspace, live dep-dbqappjboi4s73al0ul0 on bc9c08386c6369990cb5a8d44369dd2069ab431e,
finished2026-11-11T18:01:43.649857Z. That concurrent release is not this repair.
CC required integration remains failed at dependency timeout; its passing
container1507 Node/400 Python/PG E2E does not substitute for that gate. MF pins
the exact unchanged CC candidate. Do not merge MF until CC is accepted and the
pin/base/current-head checks pass. All24 live acceptance areas remain OPEN;
both publication flags stay false. No live DB administration retry, credentials,
backup retention, authority host, rights, marketplace or finance acceptance
invented. A free sleeping web service is not a continuous self-hosted worker.
