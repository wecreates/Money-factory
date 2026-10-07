
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

## Cost
The software path is free: Playwright + your existing computer + the existing GitHub repo. Etsy's normal marketplace/listing/payment fees still apply. GitHub-hosted runner usage is subject to GitHub's plan/usage limits.
