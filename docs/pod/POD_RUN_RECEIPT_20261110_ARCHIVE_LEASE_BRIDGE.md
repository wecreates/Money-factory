# POD state restore and Money Factory bridge — November 10, 2026

The existing cross-repository gate pins the merged Content Control archive
repair. A disposable PostgreSQL/loopback HTTP regression exports a processing
job with an infinite lease, restores it to a second empty database, delivers the
exact recovery receipt to the Money Factory inbox once, and attempts a retry
with a current fixture grant. The job must retain its original deadline and
attempt count, increment its fencing token, remain visible to monitoring, and
write no repair event. This extends runtime quarantine coverage to restoration;
it does not treat a recovery receipt or current grant as publication authority.

Local Node verification uses the prepared Content Control tree. The new database
case runs in the existing hosted disposable workflow, not on a live endpoint.
No live archive, authority, marketplace or continuous worker was exercised.
