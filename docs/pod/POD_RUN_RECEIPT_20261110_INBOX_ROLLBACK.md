# November 10, 2026 UTC — verify inbox rollback before pooled reuse

Starting Money Factory main was `59269225d9e7f6c5226b4b14d2e17aac6b7ca053`.
The event inbox already required exact BEGIN and COMMIT, but a resolved
SELECT substituted for ROLLBACK could return a client still holding an
open transaction to the pool. The regression failed before this change.

The inbox now requires an exact own-data-property ROLLBACK tag. Any other
response destroys the client without masking the original transaction
failure or acknowledging the event. The existing deadline and deduplication
rules are unchanged. The hosted isolated bridge test substitutes an actual
PostgreSQL SELECT after a staged insert, proves no event survives, then
retries the exact ID and observes one event.

Local Node POD suite: 301 passed, with the disposable PostgreSQL test skipped.
The hosted cross-repository run also tests the exact Content Control main
revision containing its [pool-cleanup repair](https://github.com/wecreates/content-control/pull/1158).
The pin and hosted evidence are in the associated pull request.

Neither repository change mounts the live authority or establishes production
database access, independent backups, or marketplace acceptance. Both
publication flags remain false; all 24 live acceptance areas remain open.
