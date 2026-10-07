# CYZOR Browser Farm Scaling Plan

## Initial profiles
- etsy
- redbubble
- ebay
- chrome-store
- cyzor-site
- pinterest
- youtube
- instagram
- tiktok

## Expansion model

Each business gets:
- its own persistent browser profile;
- its own queue identity;
- one active task at a time per profile to protect session state;
- parallel execution against other business profiles.

## Node 1
Run the revenue-critical authenticated workloads first:
- Etsy
- Chrome Web Store
- CYZOR site
- Redbubble
- eBay

Start with three concurrent workers. Increase only after observing stable CPU, RAM and browser crash rates.

## Additional nodes

Add another node when the existing node shows sustained resource pressure or when a business needs an isolated execution pool.

Good secondary-node candidates:
- social publishing
- marketplace research
- public monitoring
- additional POD storefronts

## Adding a business

1. Add an entry to businesses.json.
2. Create the persistent profile on the farm.
3. Complete the site's normal login and any 2FA manually.
4. Enable its task handler.
5. Add it to the queue priority table.
6. Run a read-only smoke test.
7. Enable permitted write actions.

No redesign of the farm is needed.
