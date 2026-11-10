# POD financial audit bridge verification

The cross-repository POD workflow pins Content Control at
`b4f33acbf6bd0c13dbabc6d2a0e9b1dd3c6fc5b4` and checks the newly
hardened financial intake against the existing Money Factory HTTP inbox. The
isolated PostgreSQL fixture sends a signed synthetic statement with an exact
microsecond timestamp. The same statement replays to the original ID and
creates one audit event. The real sender retains the audit as pending when
the first HTTP receipt is deliberately lost; retrying the same ID records one
inbox observation with the same ledger and authority linkage. The pull request
records the exact tested revisions and results.

The observation does not itself create or authorize Money Factory revenue. No
live provider statement, live authority or production database was exercised.
This remains fixture evidence and does not close any live acceptance area.
Both publication flags are off in the workflow.
