# CYZOR Extension Package-Diff Audit

Updated: 2026-10-06

Compared preserved public-version source backups against rebuilt release candidates where an exact current-version backup was available.

## Proven clean manifest-capability diffs

For the following extensions, candidate manifests change only the extension version and remove Chrome's generated `update_url`. Permissions, host permissions, optional permissions, optional host permissions, and background/service-worker declarations are unchanged.

| Extension | Preserved public | Candidate | Capability diff |
|---|---:|---:|---|
| FreightFill | 1.1.0 | 1.1.1 | None |
| ChangeRadar | 1.1.0 | 1.1.1 | None |
| RenewGuard | 1.1.1 | 1.1.2 | None |
| GrantRadar | 1.1.0 | 1.1.1 | None |
| ComplyWatch | 1.1.1 | 1.1.2 | None |
| AuthBridge | 1.1.1 | 1.1.2 | None |
| CredFlow | 1.1.1 | 1.1.2 | None |

## URL / endpoint diff

For those seven packages:
- no new payment/license/backend API endpoint was introduced;
- the only removed URL was Chrome's generated update URL;
- ChangeRadar additionally gained a plain `https://cyzorcreations.com` product/brand link.

This means their remaining gates are runtime correctness, website truthfulness, paid lifecycle, or backend availability—not permission expansion.

## Paid-code changes observed

FreightFill, RenewGuard, GrantRadar, ComplyWatch, AuthBridge, and CredFlow keep the same licensing/checkout endpoint paths. The meaningful Pro-code copy change is clearer trial wording.

CredFlow also corrects a misleading privacy hint. The old popup said form-fill data was “sent nowhere”; the candidate correctly says the filled details are visible to the destination portal while CredFlow itself does not submit the form.

## HireSignal caveat

The preserved HireSignal backup is version 1.0.1, while the live dashboard previously showed 1.1.1. Candidate 1.1.2 contains optional `notifications`; because we do not currently possess an exact 1.1.1 public package backup, do not claim that optional permission is newly introduced by 1.1.2. Verify the current-store permission diff during upload.

## Evidence limitations

Exact source-to-source manifest comparison was possible only for packages preserved in `CYZOR-Extension-Backups.zip`. For the other rebuilt extensions, the prior static release audit still proves:
- Manifest V3;
- manifests parse;
- JavaScript syntax passes;
- referenced resources exist;
- no remote script injection;
- no `eval` / `new Function`;
- no insecure HTTP host permissions;
- onboarding DOM suite passed across the portfolio.

Installed-Chrome certification is still required before package submission.
