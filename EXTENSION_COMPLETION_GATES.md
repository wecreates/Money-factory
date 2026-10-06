# CYZOR 19-Extension Completion Gates

Updated: 2026-10-06

## Completed and verified

- 19/19 final candidate package ZIPs exist.
- 19/19 candidate manifests are Manifest V3 and pass static package validation.
- 19/19 JavaScript syntax/resource audits pass.
- Portfolio onboarding fixture suite previously passed 209 isolated DOM checks.
- Final-v2 release manifest is reconciled against the actual ZIP bytes, including version and SHA-256.
- Public Chrome Web Store pages for all 19 target extensions were crawled.
- All 19 Chrome Web Store item IDs are mapped.
- All 19 CYZOR extension landing pages were crawled.
- Exact store-description patch text is preserved in CHROME_STORE_LISTING_PATCHES.json.
- Portfolio-wide website contradiction fixes are documented.
- OutReachMate candidate is renamed Follow-Up Tracker and removes cold-email positioning.
- Production monitor API read/list/create/delete smoke passed for change, hiring and price watches.
- Production monitor API performed an initial fetch/parser pass for all three watch kinds.
- Production license verify endpoint is live and returns valid:false for an invalid key.
- Workflow Pro checkout page renders and clearly states $0 today, first month free, then $29/month.
- Chrome Web Store API v2 release client exists and its CI tests pass.
- Phone-triggerable GitHub release workflow exists for status/upload/publish/cancel once OAuth secrets and package source are available.
- Free phone/cloud browser runner is operational for public-page audits and screenshots.

## Not complete yet — hard gates only

### Gate 1 — true installed-Chromium E2E
Required for all 19 before calling package runtime certified.

Must prove in a normal browser environment that permits unpacked extensions:
- extension loads;
- service worker/background starts where declared;
- popup opens;
- onboarding first-run flow works;
- returning-user flow works;
- no runtime/console errors;
- restricted-tab failure state is understandable;
- persistence survives popup close/reopen;
- expected permission prompts only.

Current ChatGPT container cannot certify this because its administrator policy blocks unpacked-extension/browser navigation. Do not treat that environment failure as an extension failure.

### Gate 2 — positive paid-license lifecycle
Required for AuthBridge, CredFlow, FreightFill, GrantRadar, RenewGuard and paid paths in ComplyWatch/HireSignal.

Already verified: checkout page, negative license verification route.
Still required:
- a real issued trial/license key verifies valid:true;
- activation is persisted;
- Pro UI/features unlock;
- export/calendar features actually download valid files;
- cancellation/expiry returns product to the correct state.

Do not make a real purchase solely for QA unless the account owner explicitly chooses to.

### Gate 3 — monitor scheduled/event behavior
Core monitor API is verified.
Still required:
- at least one scheduled second check after the production cadence;
- event generation when monitored content actually changes;
- badge/desktop notification behavior in installed Chrome.

### Gate 4 — production website deployment
Patch plan is complete, but cyzorcreations.com source/deployment access is not connected.
Must apply:
- remove universal free/no-upsell/local-only boilerplate where false;
- remove Quiet Tabs from active catalog while taken down;
- Resume Roast -> Resume Check;
- OutReachMate -> Follow-Up Tracker;
- remove “when listing goes live” language;
- align paid limits/features/privacy with actual packages;
- accurately disclose server-backed monitors.

### Gate 5 — real screenshots
Capture 3–5 screenshots per extension from the actual installed candidate UI after Gate 1 passes.
Do not fabricate screenshots.

### Gate 6 — Chrome Web Store submission
Once Gates 1–5 are satisfied per extension:
- upload final candidate;
- inspect Google permission/privacy diff;
- apply stale listing description where required;
- submit for review;
- enable auto-publish only for the verified candidate;
- verify the public version after approval.

## Final candidate versions

| Extension | Candidate |
|---|---:|
| AuthBridge | 1.1.2 |
| ChangeRadar | 1.1.1 |
| ComplyWatch | 1.1.2 |
| CredFlow | 1.1.2 |
| FreightFill | 1.1.1 |
| GrantRadar | 1.1.1 |
| HireSignal | 1.1.2 |
| MarginPeek | 1.0.2 |
| MockFill | 1.0.4 |
| OutReachMate | 1.0.2 |
| PixelGrab | 1.0.4 |
| PriceWatch | 1.0.4 |
| ProFill | 1.0.4 |
| RenewGuard | 1.1.2 |
| Resume Check | 1.0.5 |
| SEOPeek | 1.0.2 |
| StackPeek | 1.0.4 |
| StepDoc | 1.0.2 |
| TextGlow | 1.0.4 |

“Fully complete” means all six gates above are satisfied for all 19 and the public Chrome Web Store pages show the intended final versions.
