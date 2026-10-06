# Etsy P0 Listing Fixes

Updated: 2026-10-06

## P0 — incorrect Etsy attributes/categories

Multiple unrelated digital listings publicly show the highlight:

> Party decor for gatherings and celebrations

Confirmed on inspected listings including:
- Small Business Bookkeeping
- Cleaning Business Starter Kit
- Pet Sitting Forms
- Wedding Planner
- Debt Payoff Tracker
- Savings Challenge
- New Puppy Planner
- ADHD Daily Planner

This appears to be a systemic listing-category/attribute problem.

### Required action
Audit all 59 listings in Etsy Shop Manager and correct category + attributes before spending on ads.

Examples:
- bookkeeping / business forms → business templates / planners / forms as Etsy permits;
- finance trackers → planners / budgeting / printable organizers;
- pet forms → pet/business forms;
- health trackers → planners/logs without medical efficacy claims;
- wedding planner → wedding planning;
- stickers → stickers/decals;
- apparel → correct clothing category.

Do not leave irrelevant party-decor attributes simply because they are populated. Etsy search now uses titles, tags, attributes, descriptions, first photo and reviews holistically, so bad attributes can send mixed relevance signals.

## P0 — policy cleanup

Remove the accidental assistant sentence currently visible at the end of the shop privacy policy:

“That’s your Privacy policy done — and with it, your entire shop-policy section (returns, cancellations, privacy) is complete. Your shop is fully set up top to bottom.”

That text should never have been part of the customer-facing policy.

## P0 — title cleanup

Etsy's April 2026 guidance favors clear, scannable titles with the item and essential traits upfront, generally avoiding repeated keyword strings.

The current titles are often 20+ words and heavily repetitive. Flagship replacement titles are stored in `ETSY_FLAGSHIP_PATCHES.json`.
