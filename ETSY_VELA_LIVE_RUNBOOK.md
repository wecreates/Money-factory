# CYZOR Etsy — Vela Live Application Runbook

Updated: 2026-10-06

## Goal
Apply the completed 59-listing digital-only production pack to the existing CyzorCreations Etsy shop without Etsy developer API access.

## Files
Library:
- `/CYZOR Etsy/CYZOR-Etsy-59-Digital-Only-Production-v8.zip`
- `/CYZOR Etsy/VELA-BULK-UPDATE-v7.csv`
- `/CYZOR Etsy/59-HERO-CONTACT-SHEET-v7.jpg`
- `/CYZOR Etsy/branding/`

## Safe sequence

1. Connect CyzorCreations to Vela.
2. Export all 59 current Etsy listings from Vela and keep that export as the rollback reference.
3. Do not alter Listing ID values.
4. Merge the v8 titles/descriptions/prices/tags into Vela's exported rows.
5. Import the merged CSV into Vela.
6. Confirm each listing is treated as an update to the existing Listing ID, not as a new listing.
7. Use Vela Bulk Edit to correct Etsy category/taxonomy/attributes.
8. Change each listing to digital-download operation where supported; remove shipping/processing fields that no longer apply.
9. Replace current listing photos with the four v8 images in this exact order:
   - 01-hero.jpg
   - 02-included.jpg
   - 03-detail.jpg
   - 04-download.jpg
10. Attach the listing's actual digital product files.
11. Apply the digital-only shop banner, icon, announcement and About copy.
12. Review every listing in staging.
13. Fix any red/incomplete Vela fields.
14. Only Sync once all 59 are green and the preview matches the v8 production files.
15. Publicly verify all 59 Etsy listing pages after Sync.

## Vela CSV field mapping

Map:
- listing_id -> Listing ID
- title -> Title
- description -> Description
- price -> Price
- tags -> Tags
- image_1..image_4 -> Photo fields after converting to direct file URLs, or upload through Vela Studio
- type -> Digital/download state when the field is available; otherwise use Vela Bulk Edit / Etsy listing editor

Vela documents that CSV can add or replace photos, videos and digital files when direct-download URLs are supplied. If direct URLs are not available, complete media/file attachment in Vela before Sync.

## Quality checks before Sync

For every listing:
- no physical/POD language;
- no shipping promise;
- hero image is correct;
- actual files match description;
- no unsupported feature claim;
- 13 tags populated;
- category is relevant;
- digital file is attached;
- no old physical variation remains;
- no processing/shipping profile is accidentally attached;
- price matches the production manifest.

## Important
Vela states that synced changes cannot be automatically undone. Keep the pre-change export and review the staged changes before Sync.
