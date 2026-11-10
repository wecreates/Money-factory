# November 9, 2026 — verify the dual publication hold in bridge CI

The existing bridge workflow pins the merged Content Control repair from
[PR #1160](https://github.com/wecreates/content-control/pull/1160),
`a5c20348bc907503ad1fa33053af8a3855b72f97`. The existing
contract tests verify that status and startup smoke reject a missing or partial
publication hold. The added service fixture checks that status follows the
live flag source without enabling publication or starting a worker.

Both publication flags remain literal false in the workflow. Hosted results
and the exact merged pin are recorded on the bridge PR. These tests do not
deploy Money Factory authority, access the live database or close any of the
24 live acceptance areas.
