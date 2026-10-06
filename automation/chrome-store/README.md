# CYZOR Chrome Web Store API v2 Release Client

Uses Google's current Chrome Web Store API v2.

Required secrets/environment variables:
- `CWS_CLIENT_ID`
- `CWS_CLIENT_SECRET`
- `CWS_REFRESH_TOKEN`
- `CWS_PUBLISHER_ID`
- optional `CWS_PACKAGES_ROOT` (defaults to `release-packages`)

Do not commit OAuth secrets.

Commands:
- `node cli.mjs status all`
- `node cli.mjs upload "Resume Check"`
- `node cli.mjs publish "Resume Check"`
- `node cli.mjs cancel "Resume Check"`

Release policy: upload/status may be automated. Publish only after package/runtime/privacy checks for that extension are green. A publish call submits the item for review; Google publishes after approval using the item's existing visibility settings.
