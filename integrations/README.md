# External repository integrations

Seven upstream repositories are pinned as submodules, preserving their licenses and histories without mixing incompatible dependencies into Money Factory.

Fetch the exact recorded source revisions:

```sh
git submodule update --init --depth 1 -- integrations/vendor
python3 integrations/verify.py
```

`repositories.json` records the requested order, revision, intended integration target, and runtime blockers. `CONTENT_CONTROL_BRIDGE.json` links this inventory into the existing bridge; `PROJECT_MEMORY.md` stores the user directive.

The verifier checks source identity and revision only. A passing source check does not mean runtime readiness. No upstream install scripts, services, model downloads, publishing, or paid calls are automatically executed. Keep each runtime isolated and validate the adapter into the existing pipeline before enabling it. Do not use `git submodule update --remote` in deployment: upgrades require an explicitly reviewed pin change.

## Executable worker

Install one runtime at a time on the existing private worker:

```sh
python3 integrations/setup.py youtube-clipper-skill --runtime /path/to/persistent/runtime
python3 integrations/run.py /path/to/job.json --runtime /path/to/persistent/runtime
python3 integrations/smoke.py --runtime /path/to/persistent/runtime --report /path/to/report.json
```

Setup installs free software only; it does not buy compute, connect providers, start publishing, or download Wan weights. Linux requires Python 3.10+, Node with npm, native build tools, FFmpeg with libass, and enough disk for isolated ML packages. Wan additionally needs a provisioned CUDA GPU. Tested here with Python 3.12, Node 24.19, Bun 1.3.14 and CPU PyTorch 2.11.0. Native SQLite modules must build successfully. If node-gyp cannot extract headers due to unsupported ownership changes, extract the official matching Node headers without ownership changes and set `npm_config_nodedir` for setup/rebuild.

| Tool | Operation | Additional job fields | Verified locally |
| --- | --- | --- | --- |
| wan21 | generate | prompt, model_directory | No GPU available |
| youtube-clipper-skill | clip | input, start, end | Real clip with decoded audio/video |
| youtube-clipper-skill | captions | input, subtitles | Burned SRT; decoded pixels differ |
| openshorts | vertical | input | Real 1080×1920 MP4 with audio |
| openshorts | transcript-windows | input | Upstream sentence-boundary selection |
| claude-seo | parse-html | input | Actual title/headings extraction |
| toonflow-app | import-brief | input, workspace_directory, optional service_url | Running app import and file read-back |
| ruflo | remember-project | none | Native SQLite write and separate read-back |
| youtube-automation-agent | audit | input | Actual bundled discoverability audit |

Every job needs `tool`, `operation`, and a new `output` file path. Media inputs are local files. JSON input for `transcript-windows` contains `duration` and `transcript.segments`; `audit` accepts AgentTube's canonical content package. Clip uses the upstream stream-copy implementation, whose boundaries can vary around keyframes; it is not an exact frame-trimming guarantee.

```json
{"tool":"openshorts","operation":"vertical","input":"/worker/source.mp4","output":"/worker/jobs/job-001/vertical.mp4"}
```

The worker serializes operations to avoid concurrent ML memory exhaustion. It refuses output overwrite and requests enabling paid generation or publication. Provider secrets are not inherited by free subprocesses. Every successful operation gets an output hash receipt; media also gets decoded and probed. Receipts prove only their named operation, not complete hosted production or creative quality.

Toonflow runs privately with `TOONFLOW_DATA_DIR=/persistent/toonflow <runtime>/bun/node_modules/.bin/bun integrations/toonflow-server.ts`. It binds only loopback. Public phone access requires an authenticated reverse proxy; the upstream web app is not a full authentication boundary. No model generation provider is configured by this integration.

Content Control's `scripts/repository_tools.py` delegates here using `MONEY_FACTORY_ROOT`. The existing Remotion engine and production QA remain canonical. `local-verification.json` is local evidence, not live deployment health. AgentTube's separate upstream suite passed 47/47; provider-backed end-to-end generation remains unverified. The whole system is **not production-ready** until the registry's blockers are resolved and hosted runs pass.
