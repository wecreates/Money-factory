# Market source scope bridge verification

This CI check pins Content Control's
[market source authorization repair](https://github.com/wecreates/content-control/pull/1164).
It exercises both authorized collection modes with offline fixtures and a
substituted transport. Source permissions cannot cross marketplaces, countries,
categories, URL paths/queries or collection modes. Unscoped legacy policies
do not supply authority. A scope mismatch cannot yield passing signed intake.

No source policy is issued here, no marketplace is contacted, and both
publication switches stay false. This is regression evidence only. Real
source authorization and deployment of a live Money Factory authority remain
unverified; no live acceptance area is closed.
