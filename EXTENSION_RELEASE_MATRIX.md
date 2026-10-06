# CYZOR 19-Extension Release Matrix

Updated: 2026-10-06

Public versions below come from the rendered public Chrome Web Store pages and are the user-visible source of truth.

Legend:
- **READY_AFTER_INSTALLED_QA** — package is statically clean; needs one real installed-Chrome smoke test and fresh screenshots.
- **PAYMENT_QA_REQUIRED** — Pro/license/payment lifecycle must be verified before package release.
- **BACKEND_QA_REQUIRED** — live server/API monitoring path must be verified before package release.
- **PERMISSION_QA_REQUIRED** — changed notification/background/host-permission behavior must be verified before release.
- **WEBSITE_FIX_REQUIRED** — public site currently contradicts the package/store and should be corrected before sending more traffic.
- **LISTING_COPY_REQUIRED** — public Chrome Web Store description is still the older pre-overhaul copy.

| Extension | Public | Rebuilt | Release state | Primary blockers / next action |
|---|---:|---:|---|---|
| FreightFill | 1.1.0 | 1.1.1 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify trial→license→activation→cancel/export. Website free limit/features disagree with package. Manifest capability set is unchanged. |
| Resume Check | 1.0.3 | 1.0.4 | READY_AFTER_INSTALLED_QA + WEBSITE_FIX_REQUIRED | Installed smoke test + real screenshots. Website still uses Resume Roast naming. |
| AuthBridge | 1.1.1 | 1.1.2 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify paid activation/export. Website free/no-upsell copy conflicts with package. Manifest capability set is unchanged. |
| RenewGuard | 1.1.1 | 1.1.2 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify paid activation/export. Website still says free/no upsell and contains pre-live boilerplate. Manifest capability set is unchanged. |
| GrantRadar | 1.1.0 | 1.1.1 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify Grants.gov path plus Pro activation/export. Website generic no-upsell copy conflicts with Pro. Manifest capability set is unchanged. |
| ChangeRadar | 1.1.0 | 1.1.1 | BACKEND_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify server watch creation/check cadence/results. Website simultaneously says server-backed and local/no-server. Manifest capability set is unchanged. |
| CredFlow | 1.1.1 | 1.1.2 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Website says free/no upsell while package/store expose $29 Pro. Verify activation/export. Manifest capability set is unchanged. |
| ComplyWatch | 1.0.3 | 1.1.2 | BACKEND_QA_REQUIRED + PERMISSION_QA_REQUIRED + WEBSITE_FIX_REQUIRED + LISTING_COPY_REQUIRED | Public Store is still 1.0.3; candidate crosses an intermediate 1.1.1 build. Verify server polling, notifications, permission/privacy diff, and apply improved description. |
| MarginPeek | 1.0.0 | 1.0.2 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify calculations/product research flow + optional BYOK summary; capture screenshots; apply improved description. |
| MockFill | 1.0.1 | 1.0.3 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify native and React/Vue form fill behavior; screenshots; apply improved description. |
| OutReachMate | 1.0.1 | 1.0.2 | READY_AFTER_INSTALLED_QA + PACKAGE_RENAME_REQUIRED | Long description was partially corrected, but title/summary remain cold-email themed. Candidate 1.0.2 changes package name to Follow-Up Tracker. |
| PixelGrab | 1.0.1 | 1.0.3 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify CSS/SVG extraction across common page types; screenshots; apply improved description. |
| PriceWatch | 1.0.1 | 1.0.3 | BACKEND_QA_REQUIRED + WEBSITE_FIX_REQUIRED + LISTING_COPY_REQUIRED | Verify extraction, monitoring cadence/failures and server data flow; apply improved description. |
| ProFill | 1.0.1 | 1.0.3 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify label matching, persistence and returning user; screenshots; apply improved description. |
| SEOPeek | 1.0.0 | 1.0.2 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify local audit + optional BYOK rewrite; screenshots; apply improved description. |
| StackPeek | 1.0.1 | 1.0.3 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify detection accuracy/false positives; screenshots; apply improved description. |
| StepDoc | 1.0.0 | 1.0.2 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify click/screenshot capture and Markdown export; screenshots; apply improved description. |
| TextGlow | 1.0.1 | 1.0.3 | READY_AFTER_INSTALLED_QA + LISTING_COPY_REQUIRED | Verify Unicode formatting/accessibility behavior; screenshots; apply improved description. |
| HireSignal | 1.0.1 | 1.1.2 | BACKEND_QA_REQUIRED + PERMISSION_QA_REQUIRED + WEBSITE_FIX_REQUIRED + LISTING_COPY_REQUIRED | Public Store is still 1.0.1. Candidate adds the newer monitoring/onboarding path; verify server polling, optional notifications, permission/privacy diff, and apply improved description. |

## Public listing state

Already improved live: AuthBridge, ChangeRadar, CredFlow, FreightFill, GrantRadar, RenewGuard, Resume Check.

Partially fixed: OutReachMate (description improved; package-controlled title/summary still stale).

Stale description: ComplyWatch, HireSignal, MarginPeek, MockFill, PixelGrab, PriceWatch, ProFill, SEOPeek, StackPeek, StepDoc, TextGlow.

## Release order

### Batch A — lowest-risk packages
Resume Check, MarginPeek, MockFill, OutReachMate, PixelGrab, ProFill, SEOPeek, StackPeek, StepDoc, TextGlow.

Gate: installed-Chrome smoke test + new real-interface screenshots. Apply any stale listing description during the same submission.

### Batch B — paid workflow packages
FreightFill, AuthBridge, RenewGuard, GrantRadar, CredFlow.

Gate: successful trial/payment/license/activation/export/cancellation test; website pricing/limit copy must match package.

### Batch C — server-backed monitors
ChangeRadar, ComplyWatch, HireSignal, PriceWatch.

Gate: live backend/API monitoring success, failure-state handling, accurate privacy language; ComplyWatch/HireSignal additionally need permission/notification QA.

## Universal pre-submit checklist

1. Install rebuilt ZIP in a real Chromium profile.
2. First-run onboarding works and can be dismissed/restored.
3. Empty state and returning-user state work.
4. No console/service-worker errors.
5. No unexpected permission prompt.
6. Public description exactly matches behavior.
7. Website landing page agrees on free limit, paid features, server/local processing, and availability.
8. Capture 3–5 real UI screenshots.
9. Upload package.
10. Inspect Chrome Web Store permission/privacy diff.
11. Submit with auto-publish only when all blockers above are cleared.
12. Verify public version after approval.

Static package QA already completed for all 19 rebuilt packages: MV3 manifests parse, JavaScript syntax passes, referenced manifest resources exist, no remote-script injection/eval/new Function/insecure HTTP host permissions were found, and the onboarding suite previously passed 209 isolated DOM checks.

See also:
- `CHROME_STORE_LISTING_PATCHES.json`
- `PUBLIC_CHROME_STORE_SNAPSHOT.json`
- `EXTENSION_PACKAGE_DIFF_AUDIT.md`
- `EXTENSION_WEBSITE_PORTFOLIO_FIX.md`
