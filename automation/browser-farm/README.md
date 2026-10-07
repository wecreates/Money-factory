# CYZOR Multi-Business Browser Farm

Cloud-first, phone-controllable automation for multiple businesses.

## Architecture

- Oracle Cloud Always Free VM as the persistent host.
- Docker + Playwright browser workers.
- One persistent profile per business in `/data/profiles/<business>`.
- Durable task queue under `/data/queue`.
- Different businesses can run concurrently.
- Same-business tasks are serialized to protect profile state.
- GitHub Actions is reserved for burst/public work, not as the always-on browser host.

Example profiles:
- etsy
- redbubble
- ebay
- chrome-store
- cyzor-site

## Always-on vs always-open

The automation service stays online continuously. Persistent browser profiles preserve login/session state between jobs. Idle browser processes can be restarted on demand to save RAM. Time-sensitive businesses can be assigned dedicated hot workers.

## Free-tier scaling

Start with 3-4 concurrent browser workers on the A1 node and measure CPU/RAM. Use the two optional AMD micro instances for lightweight watchers/public checks. Do not assume unlimited free concurrency.

## Phone-first control

Expose only the authenticated task endpoint or private tunnel. ChatGPT/GitHub can enqueue jobs from a phone. The user's computer is optional.

CAPTCHA and 2FA are never bypassed; when a site requests them, the account owner completes them manually.
