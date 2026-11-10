# POD production claim scope at the authority bridge — November 10, 2026

The existing disposable PostgreSQL/loopback HTTP test renews a fixture grant
for a claimed production task. The original durable scope is eligible. When
only the stored brief's task hash changes, the same unexpired grant and lease
cannot authorize the stage or settle the job as failed. The altered row and
fence are unchanged and no outbox observation reaches the inbox.

This complements Content Control's account/platform/brief and settlement
matrix. No live database, authority, marketplace, worker or launch approval
was exercised. Both publication flags remain off.
