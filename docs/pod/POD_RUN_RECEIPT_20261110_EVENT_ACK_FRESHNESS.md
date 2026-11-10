# POD inbox acknowledgement freshness

The Money Factory inbox rejects a backwards clock before committing and checks
the signed event window again after confirmed COMMIT and connection release.
An expired or invalid final clock, or exhausted transaction deadline, withholds
the acknowledgement. It does not roll back an already confirmed commit.

The pinned Content Control outbox can send a fresh envelope for the same event
ID. The disposable HTTP/PostgreSQL round trip checks that the first response is
rejected after commit, the sender leaves its delivered marker unset, and the
retry acknowledges exactly one durable inbox row. No production database,
Money Factory authority, or marketplace is exercised.

Both publication flags stay off. This is bridge regression evidence and does
not close live acceptance or establish continuous worker availability.
