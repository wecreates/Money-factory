# November 10, 2026 — recover rejected Money Factory inbox checkouts

Started from Money Factory `3db24a210cefeb5af9d2ac44028641d5a0a24bff` and
Content Control `3fd2a4a27b3fc38a4d4ec38660641d4590917941`. The prior bridge,
integration, and container checks passed. Render's existing free Content Control
worker was live on the exact pin (`dep-dbpd1j142hec73dcgv5g`); its previous
live probe explicitly verified the dual publication hold. No overlapping POD
PR was open.

Money Factory's inbox validated query before retaining a verified release
function. If a wrapped client lacked a safe query, rejection could strand
the checked-out connection even after the acquisition deadline. It now
retains verified cleanup first and requests discard exactly once on unsafe
query, preserving the original error without executing the query getter.
An unverifiable release is still never invoked. A failed cleanup cannot
prove the external pool reclaimed its slot.

Both on-time and late client regressions failed before the fix. After repair
311 local Node tests passed with one expected PostgreSQL skip. The existing
hosted PostgreSQL round-trip additionally checks one-slot recovery: the bad
client is removed, no event is written, and retrying the same signed event
on the replacement connection stores one row. Hosted evidence is on the PR.

The workflow keeps both publication flags false. No live database path
changed, no database administration was retried, and no marketplace or
authority activation occurred. No live acceptance area was closed.
