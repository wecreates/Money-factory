# Pinned production settlement recovery — November 10, 2026

The cross-repository gate pins the exact Content Control merge and exercises
the uncertain settlement regression plus the existing real PostgreSQL production
E2E. A committed review hold followed by an adapter acknowledgment failure must
remain one review hold, with no second failure call or fabricated QA success.
The fixture also retains its ordinary review/QA, revocation and recovery checks.

All database work uses the workflow's disposable loopback PostgreSQL service.
No production authority, database, marketplace adapter, rights approval or
publication activation is verified. All 24 live acceptance areas remain open.
Both publication flags stay false. Hosted evidence is linked in this PR.
