# Offline wholesale preparation

From the repository root, with Python 3.10+ and Node 24+ already installed:

```sh
python integrations/wholesale/doctor.py
```

This runs five offline scenarios through the existing integration worker, writes to a fresh temporary directory, and prints its report path. It installs nothing, makes no provider requests and never enables production. A successful smoke is `OFFLINE_SMOKE_PASSED_PRODUCTION_BLOCKED`, not supplier or account approval. Supply `--config path/to/private-onboarding.json` to check declarations; never commit seller data or credentials.

Explicit worker jobs use `tool: wholesale`, `mode: sandbox`, one of `dry-run`, `integration-dry-run`, `onboarding-check`, `listing-draft`, `offer-contract`, local input/new output paths, and `publication_enabled`, `paid_generation_enabled`, `live_enabled` all exactly false. Run with the existing `python integrations/run.py JOB.json --runtime PATH` entry point. The wholesale dispatcher does not install or execute upstream tools; existing non-wholesale routes retain POSIX locking and source validation. Windows supports only the offline wholesale branch.

All bundled catalogs, account declarations and responses are synthetic examples. Drafts/contracts are review artifacts, not API-ready listings. Missing rights, dated quotes, feed identity/freshness, origin and economics block readiness. Supplied evidence references are declarations, not authenticated supplier approval. Returns do not imply restocking; simulation never records verified profit.

## Tests and provenance

```sh
node --test integrations/wholesale/*.test.mjs
python -m unittest discover -s integrations -p 'test_wholesale_*.py'
```

The optional recovered-core test requires an independently available manifest-verified core via MONEY_FACTORY_CORE_ROOT; it is explicitly skipped without that local artifact. No recovered core is included or claimed deployed.

Source adopted from reviewed local b459603ef72ce80df362d173f5e84bc321d30f30, including the own-property ledger replay fix. Adoption base is main fb3fc79f31726160301388106b14d8e464f876a2. Shared runner integration adds only the explicit wholesale dispatch and a fail-closed Windows import guard. Registry and other `_run` branches are unchanged. The REA branch reuses PR170's compact, lossless JSON serialization to stay within the unchanged retention limit. PR170's `_run` bridges and registry must be preserved on integration; its snapshot with the same hook passed 15 wholesale/dispatch tests, not its full adapter suite.

Real channel/SKU agreements, distributor purchasing units, dated landed quotes, permitted stock feeds, licensed assets, seller account policy/limits and fulfillment/returns terms remain external requirements. No listings, orders, accounts, payments, provider transport or production activation are authorized by this code.
