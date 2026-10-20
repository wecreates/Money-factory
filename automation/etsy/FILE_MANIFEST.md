# Single-listing digital file preflight

This is a local integrity and attachment check. It does not approve product quality, publication, pricing, payment, or a buyer download. No live command was run during development.

## The repaired gap

The old `files` command found a `product.pdf` using a substring match, silently skipped a missing promised workbook, ignored other deliverables, and printed even an empty attachment read-back as success. It also attempted direct XLSX upload, which is not in Etsy's documented supported format list.

The new command uses an exact shop/listing-bound, reviewed file manifest. It validates the entire batch before OAuth. All validated bytes are held for the later upload. Required spreadsheets from `SUPPLEMENTAL_FILES` must be present inside a reviewed ZIP. The exact archive and its declared entries are hashed; nothing is renamed, packaged, uploaded, or published by planning.

## Manifest contract

Use this shape with actual product paths and hashes. The example is intentionally blocked:

```json
{
  "schema_version": 1,
  "listing_id": "4535911896",
  "shop_id": "43299966",
  "type": "download",
  "files": [
    {
      "path": "4535911896/product.pdf",
      "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256"
    },
    {
      "path": "4535911896/Small-Business-Bookkeeping-Dashboard.zip",
      "sha256": "REPLACE_WITH_ACTUAL_ZIP_SHA256",
      "archive_entries": [
        {
          "path": "Small-Business-Bookkeeping-Dashboard.xlsx",
          "sha256": "REPLACE_WITH_ACTUAL_WORKBOOK_SHA256"
        }
      ]
    }
  ],
  "qa": {
    "status": "BLOCKED",
    "review_id": "",
    "reviewed_manifest_sha256": ""
  }
}
```

`qa` must refer to a genuine completed review of these exact assets and their listing promises. This module checks the declared review's binding; it is not a review-signature authority and cannot establish who approved it. Never turn test results or a generated manifest into product-quality approval. Include every buyer deliverable and every ZIP file entry, with correct hashes. The manifest's ordered `files` array determines attachment ranks. Use `fileManifestDigest(manifest)` to calculate the digest the review must bind to.

## Offline use

With a genuinely reviewed manifest, set `ETSY_PRODUCT_ROOT` to the artifact directory and `ETSY_FILE_MANIFEST` to the manifest file, then run:

```sh
node cli.mjs plan-files 4535911896
```

This does not request OAuth or access Etsy. It requires exactly one known listing; batch `all` is refused. It can inform the existing Vela staging workflow without an Etsy API account. It does not import into or sync Vela.

## Upload safeguards

The existing `files` command remains a consequential live operation requiring separate authorization and functioning seller access. It uses the same manifest. Before any upload, current seller metadata must confirm the exact shop ID, listing ID, and digital type. The attachment list must be explicitly empty (`count: 0`, `results: []`). Any existing or ambiguous state blocks uploads and requires seller-side reconciliation; no attachment is deleted, overwritten, or automatically retried.

Every returned upload ID must appear in the final exact attachment set. Unknown or incomplete responses fail with a reconciliation instruction. A partial network failure can still leave files attached because Etsy's individual uploads are not transactional. Reconcile before any retry. No rollback, replacement, publication, or conversion of physical listings is implemented.

## Limits and formats

[Etsy's official digital-listing help](https://help.etsy.com/hc/en-us/articles/115015628347-How-to-Manage-Your-Digital-Listings), checked 2026-10-16, documents up to five files, 20 MB each, restricted filenames up to 70 characters, and its supported type list. This implementation conservatively uses 20,000,000 bytes per attachment and rejects raw XLSX. ZIP is supported.

The dependency-free ZIP verifier deliberately accepts only ordinary single-disk stored/deflated archives with explicit local sizes, up to 512 entries and 100,000,000 uncompressed bytes. Encrypted, ZIP64, data-descriptor, unsupported, inconsistent, oversized, duplicate, missing, or unsafe archives fail closed. It never extracts to disk. This is an integrity check, not malware scanning or spreadsheet formula/functionality QA.

[Etsy's listing tutorial](https://developers.etsy.com/documentation/tutorials/listings/) and [API reference](https://developers.etsy.com/documentation/reference/) describe digital attachments and seller metadata. Actual API behavior remains untested here.

## Remaining release checks

- The actual v8 product archive was not opened or approved in this task.
- Existing Vela CSV preflight validates metadata only. Its `ok` does not prove digital type, media, attached files, or readiness to Sync.
- Existing `apply` still regenerates older listing copy. Do not use it as the authoritative v8 catalog importer.
- Real workbook functionality, actual product QA, correct listing promises/pricing, seller staging, and final public listing checks remain necessary.
- Etsy owns checkout, payment confirmation, and buyer file access. Seller attachment read-back is not payment evidence or proof a buyer downloaded a file.
- No live sale, revenue, refund reconciliation, Money Factory core ledger ingestion, or deployment is verified by these tests.
