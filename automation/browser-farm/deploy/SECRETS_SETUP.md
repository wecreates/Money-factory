
# One-Time Secrets Setup

The browser farm can be provisioned entirely from GitHub Actions after these secrets are added to the Money-factory repository.

Add under:
**GitHub → Money-factory → Settings → Secrets and variables → Actions**

Required Oracle secrets:
- `OCI_TENANCY_OCID`
- `OCI_USER_OCID`
- `OCI_FINGERPRINT`
- `OCI_API_PRIVATE_KEY`
- `OCI_REGION`
- `OCI_COMPARTMENT_OCID`
- `OCI_SSH_PUBLIC_KEY`
- `OCI_SSH_PRIVATE_KEY`

Farm control secret:
- `FARM_GITHUB_TOKEN` — fine-grained GitHub token restricted to `wecreates/Money-factory`, Contents read/write.

Do not paste any of these values into ChatGPT.

After the secrets exist:
1. Open GitHub Actions from phone.
2. Run **Provision CYZOR Browser Farm** with `plan`.
3. Confirm the plan targets one Ampere A1 instance, 2 OCPUs / 12 GB.
4. Run again with `apply`.
5. The workflow creates the VM, waits for SSH, configures the farm, and launches 3 workers.

Adding more businesses later does not require another node immediately. Enable them in `automation/browser-farm/businesses.json`. Add a second node only when sustained resource/queue thresholds justify it.
