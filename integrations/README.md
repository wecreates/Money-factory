# External repository integrations

Seven upstream repositories are pinned as submodules, preserving their licenses and histories without mixing incompatible dependencies into Money Factory.

Fetch the exact recorded source revisions:

```sh
git submodule update --init --depth 1 -- integrations/vendor
python3 integrations/verify.py
```

`repositories.json` records the requested order, revision, intended integration target, and runtime blockers. `CONTENT_CONTROL_BRIDGE.json` links this inventory into the existing bridge; `PROJECT_MEMORY.md` stores the user directive.

The verifier checks source identity and revision only. A passing source check does not mean runtime readiness. No upstream install scripts, services, model downloads, publishing, or paid calls are automatically executed. Keep each runtime isolated and validate the adapter into the existing pipeline before enabling it. Do not use `git submodule update --remote` in deployment: upgrades require an explicitly reviewed pin change.
