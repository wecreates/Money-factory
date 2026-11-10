# POD transaction completion at the Money Factory bridge — November 10, 2026

The existing disposable PostgreSQL and loopback HTTP test exercises the pinned
Content Control managed transaction and read paths. A sender-side query rejects
without a meaningful error after a real outbox insert. No SQL failure is sent
to PostgreSQL, so the sender must roll back explicitly. Nothing is delivered.
A clean retry of the same event is then held while the selected batch crosses
its configured storage cutoff during asynchronous client release. With a fresh
fixture read, exactly one signed event reaches the Money Factory inbox.

This test uses synthetic events, an isolated database and loopback HTTP only.
It verifies neither a live authority, financial result nor marketplace release.
Both publication flags remain off, and no live database access was retried.
