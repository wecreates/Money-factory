# CYZOR 19-Extension Release Matrix

Updated: 2026-10-06

Legend:
- **READY_AFTER_INSTALLED_QA** — package is statically clean; needs one real installed-Chrome smoke test and fresh screenshots.
- **PAYMENT_QA_REQUIRED** — Pro/license/payment lifecycle must be verified before package release.
- **BACKEND_QA_REQUIRED** — live server/API monitoring path must be verified before package release.
- **PERMISSION_QA_REQUIRED** — changed notification/background/host-permission behavior must be verified before release.
- **WEBSITE_FIX_REQUIRED** — public site currently contradicts the package/store and should be corrected before sending more traffic.

| Extension | Public | Rebuilt | Release state | Primary blockers / next action |
|---|---:|---:|---|---|
| FreightFill | 1.1.0 | 1.1.1 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify trial→license→activation→cancel/export. Website free limit/features disagree with package. |
| Resume Check | 1.0.3 | 1.0.4 | READY_AFTER_INSTALLED_QA + WEBSITE_FIX_REQUIRED | Installed smoke test + new screenshots. Standardize Resume Check name; remove Resume Roast naming. |
| AuthBridge | 1.1.1 | 1.1.2 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify paid activation/export. Website free limit and Pro features do not match published package behavior. |
| RenewGuard | 1.1.1 | 1.1.2 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify paid activation/export. Website still says not on Chrome Web Store and free/no upsell. |
| GrantRadar | 1.1.0 | 1.1.1 | PAYMENT_QA_REQUIRED | Verify Grants.gov search path plus Pro activation/export before upload. |
| ChangeRadar | 1.1.0 | 1.1.1 | BACKEND_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify server-side watch creation/check cadence/results. Align privacy wording with server-side monitoring. |
| CredFlow | 1.1.1 | 1.1.2 | PAYMENT_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Highest-priority contradiction cleanup: extension page says free/no upsell while sales page sells $29 Pro; free limit also conflicts with package. |
| ComplyWatch | 1.1.1 | 1.1.2 | BACKEND_QA_REQUIRED + PERMISSION_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify server polling + optional notification flow + permission disclosures. |
| MarginPeek | 1.0.1 | 1.0.2 | READY_AFTER_INSTALLED_QA | Verify marketplace/product parsing with real pages; capture useful-result screenshots. |
| MockFill | 1.0.2 | 1.0.3 | READY_AFTER_INSTALLED_QA | Verify fill behavior on native + React/Vue forms; screenshots. |
| OutReachMate | 1.0.1 | 1.0.2 | READY_AFTER_INSTALLED_QA + PACKAGE_RENAME_REQUIRED | Live description already submitted to remove cold-email positioning. Upload 1.0.2 to change package-controlled title/summary to follow-up tracking. |
| PixelGrab | 1.0.2 | 1.0.3 | READY_AFTER_INSTALLED_QA | Verify SVG/CSS extraction across common page types; screenshots. |
| PriceWatch | 1.0.2 | 1.0.3 | BACKEND_QA_REQUIRED | Verify price extraction, monitoring cadence, failure handling, and product-page compatibility. |
| ProFill | 1.0.2 | 1.0.3 | READY_AFTER_INSTALLED_QA | Verify smart label matching, empty state, persistence, returning user. |
| SEOPeek | 1.0.1 | 1.0.2 | READY_AFTER_INSTALLED_QA | Verify local audit + optional BYOK AI flow and disclosure; screenshots. |
| StackPeek | 1.0.2 | 1.0.3 | READY_AFTER_INSTALLED_QA | Verify detection accuracy and false-positive handling; screenshots. |
| StepDoc | 1.0.1 | 1.0.2 | READY_AFTER_INSTALLED_QA | Verify click capture, screenshot capture, Markdown export, and sensitive-data warning. |
| TextGlow | 1.0.2 | 1.0.3 | READY_AFTER_INSTALLED_QA | Verify Unicode formatting across target social inputs; screenshots. |
| HireSignal | 1.1.1 | 1.1.2 | BACKEND_QA_REQUIRED + PERMISSION_QA_REQUIRED + WEBSITE_FIX_REQUIRED | Verify server polling, optional notifications, and changed permission behavior. Website currently says local/free while product behavior is server-backed. |

## Release order

### Batch A — lowest-risk packages
Resume Check, MarginPeek, MockFill, OutReachMate, PixelGrab, ProFill, SEOPeek, StackPeek, StepDoc, TextGlow.

Gate: installed-Chrome smoke test + new real-interface screenshots.

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
