# November 9, 2026 — hold stale Money Factory grant responses

Started from Money Factory `ac112cb6b4964709a04a8021cc9281511080d1a2` and
Content Control `a5c20348bc907503ad1fa33053af8a3855b72f97`. The exact Content
Control main integration gate passed. Render's existing free service was live
on that revision (`dep-dbpbln5g1s2s73c7p160`); the prior exact live probe
confirmed both publication flags false. No matching POD PR was open.

The authority handler checked elapsed time only after the loader, before
snapshot validation, clock sampling, signing and response encoding. Controlled
clock regressions showed it could return HTTP 200 at expiry, after a rollback,
or after its deadline elapsed in synchronous work. It now keeps the original
deadline through encoding, samples the authority clock before emission, and
checks the actual signed grant expiry. A blocked connected request receives the
same redacted 409; it gets no new authority or renewed evidence.

Six targeted regressions failed before the repair. Afterward the focused
suite passed 42 cases and the broader local Node suite passed 308 with one
expected PostgreSQL skip. The real pinned Content Control grant resolver, over
loopback fixture HTTP, rejects a late grant response, accepts a fresh same-job
snapshot with publication forbidden, and rejects a subsequent revoked snapshot.
Hosted evidence is recorded on the associated PR.

No live Money Factory authority host was changed or verified. No changed path
to database administration was available and none was retried. No activation,
credential, marketplace operation, spend, or new infrastructure was involved.
This is not a live grant/expiry/revocation drill or a continuous worker. All 24
live acceptance areas remain open.
