# CYZOR Browser Control

A free browser-automation control plane shared between phone and computer.

## Phone mode

GitHub Actions runs public/read-only browser jobs in the cloud. Add a JSON task under `automation/browser/tasks/`; the workflow runs automatically, saves `result.json` back into the repository, and stores screenshots as a 7-day workflow artifact.

Cloud tasks intentionally reject password, OTP, token, cookie, and other credential-like form fields. Authenticated websites should use an official API/connector where available, or a one-time local browser handoff on the computer.

## Computer mode

Run `scripts/install-windows-browseract.ps1` once on Windows to install the open BrowserAct CLI. The local computer can then handle authenticated sessions, human login handoff, file uploads, screenshots, and site-specific workflows without a per-run cloud-browser fee.

## Task example

```json
{
  "id": "example.com-smoke",
  "type": "inspect",
  "url": "https://example.com",
  "actions": [{"type":"extract","selector":"h1"}],
  "screenshot": true
}
```

Allowed cloud actions: `click`, `fill` (non-sensitive fields only), `wait`, `extract`, `screenshot`.
