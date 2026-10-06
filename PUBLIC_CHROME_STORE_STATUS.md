# CYZOR Public Chrome Store Snapshot

Updated: 2026-10-06

The public Chrome Web Store pages were rendered through the free GitHub browser runner. This file records what users can actually install today.

## Improved listing copy already public
- AuthBridge 1.1.1
- ChangeRadar 1.1.0
- CredFlow 1.1.1
- FreightFill 1.1.0
- GrantRadar 1.1.0
- RenewGuard 1.1.1
- Resume Check 1.0.3

These public pages already show the revised factual descriptions from the October listing rewrite.

## Partial public fix
- **OutReachMate 1.0.1** — long description is substantially follow-up-focused, but the package-controlled title and summary still say **Follow-Ups & Cold Email / cold-email drafting**. Candidate 1.0.2 fixes the package title and summary.

## Stale public listing copy
These public pages still show the old pre-overhaul descriptions and should receive listing metadata updates:
- ComplyWatch 1.0.3
- HireSignal 1.0.1
- MarginPeek 1.0.0
- MockFill 1.0.1
- PixelGrab 1.0.1
- PriceWatch 1.0.1
- ProFill 1.0.1
- SEOPeek 1.0.0
- StackPeek 1.0.1
- StepDoc 1.0.0
- TextGlow 1.0.1

## Important discrepancy
The developer-dashboard overview previously appeared to report newer versions for several products. The public Chrome Web Store page is the user-visible source of truth and shows older versions for ComplyWatch, HireSignal, MarginPeek, MockFill, PixelGrab, PriceWatch, ProFill, SEOPeek, StackPeek, StepDoc and TextGlow.

## Public traction visible in the Store
The rendered pages explicitly showed:
- GrantRadar: 3 users
- HireSignal: 5 users
- StackPeek: 3 users
- all inspected listings: no ratings visible

Do not infer zero users for pages where Google omitted a user count.

## Release implication
Every candidate package is a real version bump over the public Store version. The next release pass should:
1. update stale metadata first where it is independent of package behavior;
2. run installed-browser QA;
3. upload candidate package;
4. inspect Google’s permission/privacy diff;
5. submit/publish only when that extension's runtime gates are green.
