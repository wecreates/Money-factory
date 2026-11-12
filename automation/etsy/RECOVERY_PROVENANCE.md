# Reused Etsy file-plan repair

Recovered from `money-factory-etsy-file-fix.zip`, SHA-256
`5fa2439e1dbb848595ac864c72c38003887bbc378a80bc7b9b067eff03a2a78d`.
The archived baseline is `e11263479d9e2fee6f6d3cb14ab430279211b2a3`.
The inspected current checkout started at
`541165fbb6cb81b64c6dca403b13d9b408a833f5`; ten selected API/source/test
files match the archived baseline after checkout line-ending normalization.
The archived patch passed `git apply --check` and was reused rather than
reimplemented. Config, catalog data, API transport and dependency pins are unchanged.

Production CLI, file-plan and ZIP verifier are unchanged from the archived
repaired source. The unit harness uses file URLs for Node `--import` on Windows.
The three independent CLI regressions were relocated into `test/`, with imports
adjusted and an optional baseline-CLI path for reproduction. Their fake fetch
handles synthetic responses only; it never contacts a provider. All test assets,
review records and credentials are explicitly synthetic.

On 2026-10-20 the three original CLI regressions failed against the unrepaired
current CLI: missing workbook was omitted, a bonus file was ignored, and empty
attachment readback counted as success. The repaired combined suite then passed
57/57 tests, with no failures or skips and no dependency install. This includes
offline planning, failure before mocked OAuth, whole-batch hashes, required
workbook ZIP entries, path/size/format bounds, listing/shop identity, occupied
attachment rejection and exact returned-ID readback.

The artifact manifest binds a supplied review to exact files; it does not
authenticate the reviewer or approve the product. No real buyer file, genuine
artifact review, seller access, upload, publication, payment or download was
performed. Actual bookkeeping PDF/workbook bytes and independent QA remain
required. Partial upload failures require reconciliation; there is no automatic
retry, replacement or rollback. Platform-format constraints are the preserved
conservative implementation documented in the original repair, not newly
validated live Etsy behavior.

This API repair is independent of the separate local-browser upload/save fix.
