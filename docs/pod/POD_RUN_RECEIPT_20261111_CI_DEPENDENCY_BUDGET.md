# Bounded required CI dependency installation — November 11, 2026

Resumed CC #1191 at 9a193536f53c776328dbab2dd9fe6c8f8fedb66c and MF #519 at
d451a5c3a66d94a7ec794e4e5e1b6f397438835e, without duplicate PRs. Both main
heads remain b9c53dd734c4c7c0ec2950b8190ac07d97823aa8 and
2becb6bed0885926ee75d215ad821e7feee0f8e3. No repository AGENTS.md was found.
Checklist, implementation-status and free-deployment blobs remain
580f8027d946fc34d4ecc28b208652f01ca5e4ac,
ee5017b86f4b13f8d597c43b4ab09ee3f21ca6db and
e4f64cc489bb4fdbc2a1e1f235f2b29507fd7676. Active criteria remain unaccepted.

The existing integration job 130635293429 passed 1507 Node tests then spent
about eight minutes in the OS dependency step before exit100 on Ubuntu mirror
DNS resolution. Its Python and production E2E steps did not run. New unrelated
successful audits do not establish recovery of configured Ubuntu downloads.
No unchanged rerun was dispatched and no database administration path changed.

The repair bounds required update plus Tesseract/font installation to a shared
120-second wall-clock budget, followed by up to five seconds before forced
process-group termination. Nonzero package results and deadline exit124 remain
failures. No OCR/font removal, ignored error, mirror/DNS/network change, package
source replacement, publication enabling, or gate bypass is introduced. This
reduces wasted free runner time; it does NOT repair upstream DNS resolution.

Six offline Python cases use executable package-manager fixtures: exact package
set on success; update failure stops installation; installation failure remains
an error; stalled update/installation expire; and the workflow uses the bounded
gate without continue-on-error. Their fixture scales the immutable production
timeout to 0.15 seconds; no live package manager or network is used in unit tests.
All six pass locally. bash syntax and existing workflow-control verification pass.
Hosted results for the new heads must be recorded in these existing PRs before
merge. Older passing jobs do not certify the new heads.

Read-only Render metadata at 08:46 PST still reports the existing free Docker
service and live dep-dbq72t0473hc73ck7p9g on b9c53dd, finished
2026-11-11T13:46:47.833978Z. No new repair is deployed. The prior public status
at15:57Z explicitly verified both publication flags off; that is a historical
observation, not a fresh runtime probe or proof of live acceptance.

All24 acceptance areas remain OPEN. Retained backup/recovery, live MF authority,
real accounts/current grants, rights, official templates, independent QA,
authorized marketplace adapters, reconciliation, phone acceptance and measured
capacity remain unverified. No credentials, approvals, revenue or live acceptance
are fabricated. A free sleeping web service is not an always-on worker. Keep
both publication flags false and leave completion automation unchanged.
