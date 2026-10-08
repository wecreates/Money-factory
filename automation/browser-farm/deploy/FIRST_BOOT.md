# CYZOR Browser Farm — First Boot

Once the Oracle VM exists, add these GitHub Actions secrets:

- `ORACLE_HOST` — VM public IP
- `ORACLE_USER` — normally `ubuntu`
- `ORACLE_SSH_KEY` — private SSH key for the VM
- `FARM_GITHUB_TOKEN` — fine-grained token limited to `wecreates/Money-factory` with Contents read/write

Never paste these secrets into ChatGPT.

Then from your phone:

1. Open GitHub → `wecreates/Money-factory`.
2. Open **Actions**.
3. Run **Deploy Browser Farm to Oracle**.
4. Leave `max_parallel=3` on the first boot.
5. Wait for the workflow to turn green.

The first validation target is the public smoke task under:
`automation/browser-farm/cloud-queue/`

After public smoke passes, attach authenticated business profiles one at a time.

Recommended expansion order:
1. Etsy
2. Chrome Web Store
3. CYZOR site
4. Redbubble
5. Other POD storefronts
6. Additional businesses as capacity is added

Scale workers only after checking RAM/CPU. Add more browser-farm nodes over time as more businesses are added.
