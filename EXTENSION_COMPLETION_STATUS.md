# CYZOR 19-Extension Completion Status

Updated: 2026-10-06

## Proven complete from phone/cloud/static QA

### Package quality
- Latest candidate set: 19/19 packages pass Manifest V3/resource/JavaScript/risky-code/insecure-host static QA.
- Onboarding: 209/209 checks pass across all 19, 0 errors.
- Seven free-only products were further cleaned so unused `pro.js` and dead Pro upsell UI are removed:
  - MockFill 1.0.4
  - PixelGrab 1.0.4
  - PriceWatch 1.0.4
  - ProFill 1.0.4
  - Resume Check 1.0.5
  - StackPeek 1.0.4
  - TextGlow 1.0.4
- Latest authoritative bundle: `CYZOR-Public-Release-Candidates-2026-10-06-final.zip`
- Bundle SHA-256: `71eec010c8f31211c49bb64bad155225ee077034bf90cea69507ecb7e1480e87`

### Public Chrome Web Store
All 19 target extensions have live public Store pages and their extension IDs are mapped in `CHROME_WEB_STORE_IDS.json`.

Public rendered pages were audited and real public versions recorded in `PUBLIC_CHROME_STORE_SNAPSHOT.json`.

Improved listing copy already live:
- AuthBridge
- ChangeRadar
- CredFlow
- FreightFill
- GrantRadar
- RenewGuard
- Resume Check

OutReachMate is partially fixed:
- long description is improved;
- package-controlled title/summary still need candidate 1.0.2 to remove cold-email positioning.

Stale descriptions still requiring Store metadata update:
- ComplyWatch
- HireSignal
- MarginPeek
- MockFill
- PixelGrab
- PriceWatch
- ProFill
- SEOPeek
- StackPeek
- StepDoc
- TextGlow

Exact replacement listing copy for all 19 is in `CHROME_STORE_LISTING_PATCHES.json`.

### Server-backed monitor API
Production smoke passed:
- watch list contract
- event list contract
- unseen event query
- create `change` watch
- create `hiring` watch
- create `price` watch
- initial source fetch/parsing
- delete watches
- final cleanup to zero watches

No smoke-test watches were left behind.

### Workflow Pro license endpoint
`POST /tools/pro/verify` exists and returns HTTP 200 `{"valid":false}` for a deliberately invalid key, matching extension expectations.

### Workflow Pro checkout page
The public checkout renders successfully and states:
- $0 due today
- first month free
- then $29/month
- cancel before trial ends to avoid first charge
- card entry through Helcim
- one key across seven Workflow Pro extensions

No payment was attempted during QA.

### GrantRadar
The exact Grants.gov endpoint and payload used by the extension were tested live:
- HTTP 200
- expected `data.oppHits` array
- real current posted grant records returned

## Production website problems now proven

### All 19 sideload ZIPs are stale
Every ZIP linked from the live CYZOR extension pages currently serves **version 1.0.0**, including products whose Chrome Web Store versions are already newer.

Therefore the website's current sideload path must not be treated as the current release channel.

Required fix:
1. remove/de-emphasize `OR SIDELOAD THE ZIP` from normal customer flow;
2. either replace all 19 website ZIPs with the final release packages or move manual ZIP install behind a developer-only section;
3. remove “when the listing goes live” wording because all 19 are already live in the Store.

### Shared template contradictions
All 19 pages still contain generic boilerplate such as:
- free forever;
- no upsell path;
- runs locally;
- nothing stored on servers;
- listing will go live later.

Those statements are false for some paid/server-backed extensions. The exact portfolio-wide correction is in `EXTENSION_WEBSITE_PORTFOLIO_FIX.md`.

### Naming
- OutReachMate website/catalog still uses cold-email language.
- Resume Check website/catalog still uses Resume Roast in places.
- Quiet Tabs is still listed in the website extension catalog even though it is the taken-down item.

## Remaining blockers that genuinely require external capability

1. **Installed Chromium certification of candidate ZIPs**
   - popup render
   - first-run/returning-user state in real extension context
   - service-worker/background runtime
   - actual notification permission delivery
   - fresh product screenshots
   Current ChatGPT sandbox Chromium is configured to suppress unpacked extension loading, so it cannot be used as proof.

2. **Valid Workflow Pro lifecycle**
   - real valid license
   - unlock across paid products
   - exports/calendar under Pro
   - cancellation / post-trial behavior
   We will not create a paid subscription or enter card details without explicit user authorization.

3. **Production website source/host**
   - no writable source for `cyzorcreations.com` is currently connected.
   - the editable ChatGPT Site artifact is a separate preview and is intentionally not being substituted for production.

4. **Chrome Web Store release credentials**
   The v2 release client and phone-triggerable workflow are built and tested. It still needs:
   - `CWS_CLIENT_ID`
   - `CWS_CLIENT_SECRET`
   - `CWS_REFRESH_TOKEN`
   - `CWS_PUBLISHER_ID`
   stored as GitHub Actions secrets, or an authenticated local BrowserAct/Chrome session.

5. **Google review**
   Public completion cannot be claimed until candidate uploads are reviewed/approved and the public Store pages show the intended versions.

## Completion rule
“Fully complete” means:
- correct candidate installed and tested;
- correct Store metadata/screenshots;
- website contradictions fixed;
- candidate submitted;
- Google approved;
- public Store version re-verified;
- no stale sideload package remains in the normal website flow.
