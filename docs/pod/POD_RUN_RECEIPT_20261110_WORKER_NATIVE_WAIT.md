# Pinned worker polling cancellation — November 10, 2026

The cross-repository workflow pins the exact Content Control merge and verifies
native cancellation through polling waits after healthy idle and dependency
failures. It also verifies runtime stop after a recovery callback shadows its
signal and forwarding-listener cleanup after an ordinary interval.
The existing publisher-cancellation suite also verifies that synthetic abort
events cannot accelerate polling or consume the real cancellation listener.

The existing bridge, restricted PostgreSQL claim, and production/review E2E
fixtures remain unchanged. Passing lifecycle fixtures do not establish live
worker uptime, current authority, marketplace permission or accepted creative QA.

Exact hosted, merge and Render evidence is linked in the PR. No live database,
publication setting, provider, credential or network restriction is changed.
All 24 live acceptance areas remain open.
