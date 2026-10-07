
# CYZOR GitHub Browser Fleet

Default zero-new-account browser automation runtime.

## Features
- Parallel Playwright jobs through GitHub Actions matrix jobs.
- One isolated runner per business.
- Frequent group scheduled every 15 minutes.
- Normal group scheduled every 2 hours.
- Manual phone-triggered runs.
- Screenshots and result artifacts.
- No Oracle, Vela, Browserbase, or paid browser service required.

## Current businesses
Configured in `businesses.json`:
- Etsy — enabled
- Chrome Store — enabled
- CYZOR site — enabled
- Redbubble — disabled until needed
- eBay — disabled until needed

Add more businesses by adding a registry entry and task JSON.

## Authentication
Public tasks work immediately.

Authenticated sites can optionally use a GitHub Actions secret named `BROWSER_SESSIONS_JSON`. It should be a JSON object mapping business IDs to base64-encoded Playwright storage-state JSON.

Never place passwords, OTP codes, cookies, recovery codes, or session state in source files or chat.

When a saved login expires or a site requires CAPTCHA/2FA, the account owner must refresh that site's session manually. This system does not bypass account security challenges.

## Scaling
Different businesses can run simultaneously. The workflow currently caps each matrix execution at 10 parallel jobs.

This is deliberately optimized for free hosted infrastructure. It is not a permanent 24/7 browser host: GitHub-hosted runners are ephemeral and subject to GitHub plan usage/concurrency limits. Use frequent scheduled runs while businesses are pre-revenue, then migrate only proven revenue-producing workflows to persistent compute if they actually need it.
