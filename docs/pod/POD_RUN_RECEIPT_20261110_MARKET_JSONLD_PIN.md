# November 10, 2026 — verify the market snapshot repair in bridge CI

The bridge workflow pins the merged Content Control market-intake repair
from [PR #1162](https://github.com/wecreates/content-control/pull/1162),
`51ba2dc16a138f321dcea06917017c7835c4ea0e`.
It runs the pinned market-intake Python suite with the existing image
dependencies. Signed fixture snapshots test source binding, exact decimal
prices, duplicate decoded keys, and malformed offers without requesting a
marketplace or inferring missing observations.

Both workflow publication flags remain literal false. Hosted verification and
the exact merged revision are recorded on the bridge PR. No live market
collection, authority deployment, rights clearance, or acceptance is claimed.
