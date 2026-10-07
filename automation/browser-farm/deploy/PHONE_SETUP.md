# CYZOR Browser Farm — Phone-First First Node

## Goal
Bring one always-on free Oracle Cloud node online without depending on a personal computer.

## 1. Create the VM from your phone
In Oracle Cloud create an Always Free Ampere A1 Compute instance when capacity is available.

Recommended starting shape:
- Ubuntu
- Ampere A1
- 2 OCPUs
- 12 GB RAM
- Always Free eligible
- default boot disk unless you need more storage later

Do not open the browser-farm HTTP port to the public internet. The farm polls GitHub outbound.

## 2. SSH into the VM
Use Oracle Cloud Shell from the browser on your phone, or another SSH client you already use.

## 3. Install the farm
Run:

```bash
sudo bash -c 'curl -fsSL https://raw.githubusercontent.com/wecreates/Money-factory/main/automation/browser-farm/deploy/oracle-cloud-init.sh | bash'
```

The installer clones Money-factory and creates:
`/opt/cyzor/Money-factory/automation/browser-farm/.env`

It intentionally stops before launching until the GitHub token is configured.

## 4. Create a GitHub token
Create a fine-grained GitHub token restricted to:
- repository: wecreates/Money-factory
- Contents: Read and write

Do not paste that token into ChatGPT.

In the VM edit:
`/opt/cyzor/Money-factory/automation/browser-farm/.env`

Set:
```
GITHUB_TOKEN=<token>
MAX_PARALLEL=3
HEADLESS=true
```

Start conservatively at 3 workers. Raise concurrency after observing actual memory use.

## 5. Start the service
```bash
cd /opt/cyzor/Money-factory/automation/browser-farm
sudo docker compose up -d --build
sudo docker compose logs -f
```

## 6. Smoke test
Commit a task JSON into:
`automation/browser-farm/cloud-queue/`

The included example checks Example Domain.

Expected path:
GitHub queue → Oracle poller → worker → Playwright → durable result under `/data/queue/done/`.

## 7. Add businesses one at a time
After the public smoke passes:
1. etsy
2. chrome-store
3. cyzor-site
4. redbubble / later POD storefronts
5. other businesses

Each gets its own persistent profile:
`/data/profiles/<business>`

## Security
- Never place passwords, cookies, OTPs, recovery codes, or API secrets in task JSON.
- CAPTCHA/2FA are manual owner checkpoints.
- Do not expose port 8787 publicly.
- The VM makes outbound GitHub requests; no public inbound task endpoint is required.
