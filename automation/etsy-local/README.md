
# CYZOR Etsy Local Automation — Free Path

This is the no-subscription alternative to Vela.

## Architecture
- **Authenticated Etsy work:** local Playwright + a persistent Chrome profile on your computer.
- **Public QA/research:** the existing GitHub Actions browser runner.
- **Task source:** JSON files in this folder / generated from the 59-listing manifest.

## Why local Chrome
Etsy rejected the seller's API app twice. Browser automation can still perform the same user-directed shop-admin actions without paying for a bulk-edit service.

## One-time setup
1. Run `scripts/install-windows.ps1`.
2. Run an Etsy task.
3. Chrome opens.
4. Sign in to Etsy manually once.
5. Complete 2FA/CAPTCHA manually if Etsy requests it.
6. The dedicated profile stays signed in for later tasks.

## Supported actions
- update listing title
- description
- price
- tags
- switch to digital where the Etsy editor exposes that option
- upload listing images
- upload digital files
- update shop title/announcement
- create sections
- public verification

## Safety / limits
- Does not bypass CAPTCHA, 2FA, or Etsy security challenges.
- No account passwords, cookies, OTPs, or recovery codes belong in GitHub task files.
- Etsy page markup changes over time; selectors may need maintenance.
- Use the prepared digital-only manifest as the source of truth.
- Keep publication/replacement actions reversible until public verification passes.
- When `patch.files` or `patch.images` is supplied, every requested path must be
  a nonempty local regular file. Validation happens before Chrome launches;
  empty lists and missing files are errors, rather than skipped uploads.
- Listing updates require an unambiguous digital/image upload control for the
  requested files, an enabled save button, and a fresh save confirmation.
  Missing or changed Etsy markup fails the task instead of reporting success.
  After an unconfirmed save, inspect the listing before retrying: some changes
  may already have reached Etsy. There is no automatic retry or rollback.
- `EDITOR_READBACK_CONFIRMED` means a fresh editor save confirmation followed
  by a reload and matching requested metadata and attachment records. It does
  not verify attachment bytes, product quality, buyer downloads, or sales.
- Uploads must finish before Save: no visible progress/busy indicator, no
  error/rejection alert, and one new durable record for every requested filename.
  The editor must expose unique Digital files/Downloadable files and
  Photos/Listing images groups. Both groups are inventoried before uploads;
  existing durable identities must remain before Save and after reload. Ambiguous
  inventory blocks the task. Uploads here add assets; this does not implement
  removal or replacement of existing buyer assets.
  Digital files require an exact filename-named download link with an HTTP(S)
  href and a download attribute; images require an exact filename-named image
  with an HTTP(S) source. Blob/data previews, duplicate names, unchanged old
  records, partial batches and missing records fail closed. After reload, the
  same attachment identities must still be present.
- These conservative semantic selectors are an unverified compatibility contract,
  not a claim about current Etsy markup. A valid upload with renamed files,
  non-download links, changed signed URLs or different image names can fail
  verification. Inspect the editor before retrying; do not weaken checks to a
  generic toast or filename appearing anywhere on the page.
- Title, description and price require unique exact labels and value readback.
  Digital selection requires a checked radio named Digital, Digital files, or
  Digital item. Tags require an accessible Tags group, one textbox and explicit
  Remove tag <value> buttons. No tag interaction failure is ignored. Unknown
  fields, unsupported types and invalid values are rejected before Chrome starts.
- Saves that were clicked but cannot be reconciled through reload/readback are
  failures with an explicit reconcile-before-retry message. There is no automatic
  resubmission, deletion, rollback, publication or buyer-download verification.

## Offline regression checks
Run `npm test` in this directory. The tests use synthetic filenames and a pure
browser transport double. They do not launch Playwright, access a Chrome profile,
contact Etsy or establish live selector compatibility. Run a separately authorized
live verification before using this runner for a real batch.

## Cost
The software path is free: Playwright + your existing computer + the existing GitHub repo. Etsy's normal marketplace/listing/payment fees still apply. GitHub-hosted runner usage is subject to GitHub's plan/usage limits.



## Shop and section save checks
- Shop patches accept only `title` and `announcement`, with at least one field.
  Titles must be nonempty strings. An explicitly empty announcement clears it;
  it is not silently skipped. Both require unique visible exact labels (`Shop
  title`, `Announcement`), successful fill and value readback.
- Section creation requires a unique `Manage sections` button and dialog, an
  accessible `Sections` list whose visible listitems contain only section names,
  an `Add section` or `New section` button, and an exact `Section name` label.
  Existing duplicate names, an already-present requested name, unknown controls
  or an ambiguous inventory stop before Save. This is not an upsert operation.
- Both actions require a unique visible enabled Save control and a fresh,
  unambiguous accessible status reporting saved changes/shop or section creation.
  Visible alerts or busy indicators block confirmation. After Save, reload must
  retain the same URL. Shop values must match exactly; section creation reopens
  Manage sections and requires exactly the prior inventory plus the new name.
- `SHOP_READBACK_CONFIRMED` and `SECTION_READBACK_CONFIRMED` describe those editor
  readbacks only. These selectors are a synthetic, unverified compatibility
  contract, not a certification of current Etsy markup or a public-shop check.
  Unknown markup fails closed. Action/readback waits are bounded. An attempted
  save with uncertain outcome requires inspection before retrying, as it may
  already have taken effect. No automatic save retry, deletion or rollback runs.
