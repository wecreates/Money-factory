# CYZOR Portfolio-Wide Extension Website Fix

Updated: 2026-10-06

The live crawl of all 19 extension landing pages found a shared template problem.

## Remove or conditionalize these boilerplate claims

The current extension-page template repeats all or most of the following on every product:
- “This extension is free with no signup.”
- “nothing stored on our servers.”
- “runs locally in your browser.”
- “Free forever — the trade behind that.”
- “This extension is free with no upsell path.”
- “No cloud infrastructure to fund, no per-user cost.”
- sideload troubleshooting that says “install from the Chrome Web Store instead when the listing goes live.”

These claims are not universally true and now contradict several live products.

## Replace with capability-aware modules

### Module A — local-only free extension
Use for products whose actual code is local-only and has no paid tier.

Suggested structure:
- **Install:** primary Chrome Web Store button; sideload only as a secondary developer option.
- **Privacy:** “Core processing happens in your browser. CYZOR does not receive the page content you process unless you explicitly use an external/BYOK feature described below.”
- **Pricing:** “Free.”
- Do not say “when the listing goes live”; it is already live.

### Module B — local core + optional paid license
Use for AuthBridge, CredFlow, FreightFill, GrantRadar, RenewGuard and any other package with Workflow Pro.

Suggested structure:
- **Start free:** state the exact free cap from shipping code.
- **Optional Workflow Pro:** list only verified paid features.
- **Pricing:** “First month free; card required. Then $29/month. Cancel before the trial ends to avoid the first charge. Checkout shows current terms.”
- **Privacy:** distinguish local working data from license verification traffic.
- Never say “no upsell path.”

### Module C — server-backed monitoring
Use for ChangeRadar, ComplyWatch, HireSignal, PriceWatch.

Suggested structure:
- state that monitoring uses CYZOR/server-side checks;
- state exactly which selected URL/title/device/watch-list identifier is sent;
- state cadence honestly;
- state that checks can continue while Chrome is closed only when backend verification confirms it;
- do not claim the extension is wholly local or that CYZOR stores nothing.

### Module D — BYOK external service
Use where a feature sends user-selected text/data to a third-party API with the user's own key, such as optional SEOPeek AI rewriting.
- Core feature remains local when true.
- Explicitly identify what is sent only when the user invokes the optional feature.
- State that provider charges/policies may apply.

## Global merchandising fixes

1. Remove Quiet Tabs from the active extension catalog while its Chrome Web Store item is taken down.
2. Rename **Resume Roast** everywhere to **Resume Check**.
3. Rename **OutReachMate — Follow-Ups & Cold Email** to **OutReachMate — Follow-Up Tracker** and remove cold-email drafting/cadence copy.
4. Replace “OR SIDELOAD THE ZIP” as the dominant secondary path with a smaller **Developer / manual install** disclosure.
5. Every page already has a live Chrome Web Store URL; remove “when the listing goes live” copy from all 19 pages.
6. Replace generic “V1” labels with either the real public version or omit version from marketing pages.
7. Add a dedicated support link per extension instead of only generic site navigation.
8. Use 3–5 real product screenshots per product page and Chrome listing.
9. Align related-product cards with current names; ChangeRadar and other pages still cross-link to “Resume Roast,” and several pages still describe OutReachMate as cold email.
10. Scope the site-wide “files never upload / work runs on your device” promise so it does not falsely describe server-backed monitoring products.

## Source-of-truth rule

For every extension, public website copy must be generated from a structured product record with these fields:
- product_name
- public_version
- store_url
- free_limit
- paid_price
- paid_features
- local_data
- remote_data
- external_providers
- permissions
- monitoring_cadence
- account_required
- support_url
- privacy_url

Do not hand-maintain contradictory copies on catalog card, extension detail page, vertical landing page and Chrome listing.
