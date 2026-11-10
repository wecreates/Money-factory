# November 9, 2026 — exercise request-time task binding across the bridge

The bridge workflow pins the exact merged Content Control grant-scope repair
from [PR #1161](https://github.com/wecreates/content-control/pull/1161),
`3fd2a4a27b3fc38a4d4ec38660641d4590917941`.
The loopback fixture uses the Money Factory authority and pinned Content
Control grant resolver. If the task changes during lookup, the first signed
response does not match the initiating task. A second, fresh lookup can
authorize the replacement task without granting publication.

The new test failed against the previous pin and passed against the repaired
consumer. Both workflow publication flags remain literal false. This fixture
does not mount live authority, run a production database or grant marketplace
access. Hosted results and the merged pin are recorded on the bridge PR. All
24 live acceptance areas remain open.
