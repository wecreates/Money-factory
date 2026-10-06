# CYZOR Etsy Overhaul Client

Shop ID: 43299966

Uses Etsy Open API v3 Seller App OAuth.

Required GitHub/host secrets:
- ETSY_API_KEY
- ETSY_SHARED_SECRET
- ETSY_CLIENT_ID
- ETSY_REFRESH_TOKEN

Required OAuth scopes:
- shops_r
- shops_w
- listings_r
- listings_w

Commands:
- `node cli.mjs diff all` — read current flagship listings and print before/desired changes
- `node cli.mjs apply "Coffee Bean Sticker"` — apply one prepared flagship patch
- `node cli.mjs shop` — update shop title + announcement
- `node cli.mjs sections` — create the planned shop sections

Safety:
- no delete endpoint is implemented;
- no listing is deactivated by this client;
- patches are explicit;
- use diff before apply.
