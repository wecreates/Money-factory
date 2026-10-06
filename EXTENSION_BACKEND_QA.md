# CYZOR Extension Backend QA Evidence

Updated: 2026-10-06

## Verified production monitor API

A self-cleaning GitHub Actions smoke test exercised the exact production endpoints used by ChangeRadar, ComplyWatch, HireSignal and PriceWatch.

Client ID was isolated under `cyzor-release-smoke-*`.

### Read contracts
- `GET /api/v1/ext/watch?clientId=...` → HTTP 200, `{"watches":[]}`
- `GET /api/v1/ext/events?clientId=...` → HTTP 200, `{"events":[]}`
- unseen-events query → HTTP 200 with the expected events array contract

### Create contracts
Disposable watches were created against `https://example.com/`:
- `kind=change` → HTTP 200, watch ID returned, initial page text captured
- `kind=hiring` → HTTP 200, watch ID returned, initial value `0 job signals`
- `kind=price` → HTTP 200, watch ID returned, initial value `(no price found)`

The backend performed an initial check during watch creation and returned the watches as `status=active`.

### Delete / cleanup contract
All three disposable watches were deleted:
- each DELETE returned HTTP 200 `{"ok":true}`
- final watch-list query returned an empty list

No test watches were left behind.

## Verified license endpoint
`POST https://cyzorcreations.com/tools/pro/verify` with a deliberately invalid smoke-test key returned:
- HTTP 200
- `{"valid":false}`

This proves the route exists and its negative-key contract matches the extension code.

## What this clears
The following are now verified against production:
- monitor API availability;
- watch-list response contract;
- event-list response contract;
- watch creation for change/hiring/price kinds;
- initial fetch/parser execution;
- watch deletion/cleanup;
- license verification endpoint availability.

## Remaining backend/runtime checks
Still not proven:
1. a scheduled second check after the advertised cadence;
2. creation of an event after a monitored page actually changes;
3. toolbar badge/desktop notification delivery inside an installed browser;
4. Pro behavior with a genuinely issued valid Workflow Pro license.

Those remaining checks are narrower than the original generic “backend QA required” blocker.
