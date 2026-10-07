# CYZOR Etsy Digital-Only Production v8

Updated: 2026-10-06

## Production master

Persistent Library archive:
`/CYZOR Etsy/CYZOR-Etsy-59-Digital-Only-Production-v8.zip`

SHA-256:
`3cf22fda23fb5d6923306065c57270e3df789b914af78beeda07a7c9a480e612`

## Completed

- 59/59 current listings rebuilt for digital-download-only operation.
- POD removed from the Etsy catalog strategy.
- 59/59 have conversion-focused listing titles.
- 59/59 have 13 tags.
- 59/59 have digital-only descriptions.
- 59/59 have price targets.
- 59/59 have four 2000px-wide listing images.
- First-image retail headlines are shorter than SEO titles for thumbnail readability.
- Spreadsheet claims remain only where an XLSX is actually included.
- Hyperlinked/editable/count claims were removed unless supported.
- Physical sticker/apparel concepts became original digital sticker/clipart packs.
- Sticker products include transparent PNG assets.
- Physical wall art became original high-resolution printable JPG + PDF collections.
- Store branding pack added:
  - 1600x400 big banner
  - 1600x213 mini banner
  - 500x500 shop icon
  - 1520x200 order receipt banner
- Shop title/announcement/About copy rewritten for a 100% digital storefront.
- Portfolio hero-image contact sheet reviewed for visual consistency.

## Final QA

- listing_count = 59
- all_digital = true
- all_have_13_tags = true
- all_have_4_images = true
- unsupported_claims = 0

## Current live blocker

The production files are complete, but the live Etsy storefront still needs authenticated seller-side application.

Preferred application route:
Vela -> Etsy, because the owner's Etsy developer API applications were rejected.

Vela can bulk edit titles, descriptions, pricing, categories, attributes, and photos, and its CSV import supports direct media/digital-file URLs. Existing listing IDs must remain unchanged when updating existing listings.

No live Sync should occur until the entire staging batch is reviewed.
