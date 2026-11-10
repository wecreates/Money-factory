# November 10, 2026 UTC — Content Control transaction boundary pin

The existing cross-repository gate now pins Content Control main at
`4679e07f02646635437afc48ea99093583f061fc`, which contains [managed transaction
start verification](https://github.com/wecreates/content-control/pull/1155)
and [archive snapshot transaction
verification](https://github.com/wecreates/content-control/pull/1156).
Both Content Control changes passed integration and container CI before merge,
including real disposable PostgreSQL command tags.

The workflow explicitly checks the pinned managed transaction and restore
boundaries alongside its existing archive, metrics, capacity and current
authority contracts. Content Control runs its own real database fault fixtures;
Money Factory's existing distinct disposable bridge database checks the
cross-repository grant and outbox round trip. Local checks on the combined
source passed 300 Money Factory Node cases (one expected PostgreSQL skip) and
53 focused Content Control cases (two expected PostgreSQL skips). The pull
request records the hosted run and merge result.

This is a CI pin, not Money Factory production deployment or a storage/recovery
drill. No production database administration was retried; no changed authorized
access path was found. Publication flags remain false. All 24 live acceptance
areas remain open; no continuously running worker is claimed.
