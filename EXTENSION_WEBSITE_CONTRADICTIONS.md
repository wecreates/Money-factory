# CYZOR Extension Website Contradiction Register

Updated: 2026-10-06

This register tracks public website claims that currently conflict with Chrome Web Store state or rebuilt package behavior.

## P0 — fix before driving traffic

### CredFlow
- `/extensions/credflow` says **free forever** and **no upsell path**.
- `/credflow` sells **Workflow Pro at $29/mo**.
- Paid landing page says free tier is **1 provider**.
- Verified package behavior from the release audit is **5 providers free**, with Pro unlocking unlimited providers + CSV/calendar exports.
- Action: choose one source of truth and update both website surfaces plus store copy to match it.

### RenewGuard
- `/extensions/renewguard-contract-renewals` says **not on the Chrome Web Store yet**.
- The extension is already published.
- The same page says the extension is free/no upsell, while the rebuilt/published monetization path includes Pro.
- Action: replace sideload-first messaging with the live store install path and align pricing/limits.

### AuthBridge
- Sales page says free tier is **1 provider** and Pro includes whole-clinic dashboard, eligibility re-check reminders, background alerts/audit log.
- Verified package audit describes free limit as **10 authorizations** and Pro as unlimited authorizations + register/activity-log CSV exports.
- Action: make pricing limits and Pro feature list match the code actually shipping.

### FreightFill
- Sales page says free tier stores **up to 5 loads** and Pro includes shared templates/audit log.
- Verified package audit says **10 loads free**, then unlimited loads + load-list CSV.
- Action: align free cap and paid feature list before package release.

### HireSignal
- Extension website page says it **runs locally**, has **no server cost**, and is **free forever with no upsell**.
- Product/store positioning says server-side checks continue when Chrome is closed.
- Action: remove generic local-only boilerplate and disclose exactly what is sent to the server and how checks run.

## P1 — product/store naming and positioning

### OutReachMate
- Website catalog still calls it **“Follow-Ups & Cold Email.”**
- New product direction is follow-up tracking; cold email is explicitly retired.
- Store description correction has been submitted, but package-controlled title/summary require rebuilt package 1.0.2.
- Action: rename website catalog/card/page to **OutReachMate — Follow-Up Tracker** and remove cold-email generator references.

### Resume Check
- Website catalog still uses **Resume Roast — Instant Resume Check**.
- Chrome Web Store/product package uses **Resume Check**.
- Action: standardize all website/store/package references to **Resume Check**.

## P1 — privacy architecture contradictions

### ChangeRadar / ComplyWatch / HireSignal / PriceWatch
- CYZOR’s global website language strongly emphasizes “nothing uploads” and local-only behavior.
- These monitor products rely on remote/server-side checks or external data.
- Action: keep the global local-processing promise scoped to tools that actually run locally; each monitoring product page must explicitly state what metadata is sent, what remains local, check cadence, and whether monitoring continues when Chrome is closed.

## P2 — merchandising gaps across the catalog
- Catalog still exposes stale titles/descriptions on several extension cards.
- Store pages historically used one screenshot each.
- Homepage/support links are too generic.
- Action: dedicated landing/support route per extension, 3–5 real screenshots, consistent naming, truthful free/paid callouts, and cross-links to related CYZOR tools.

## Release rule
No extension should be promoted harder until the website, store listing, and actual package agree on:
- current availability,
- free limits,
- paid limits/features,
- data flow/privacy,
- monitoring cadence,
- account requirements,
- and product name.
