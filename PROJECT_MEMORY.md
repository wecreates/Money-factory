# Money Factory project memory

## 2026-10-12: ordered repository additions

Chris requested these seven repositories be added to Money Factory and memory, one by one in the following order. The canonical machine-readable record is `integrations/repositories.json`.

1. [wan21](https://github.com/Wan-Video/Wan2.1) — Content Control asset generation.
2. [youtube-clipper-skill](https://github.com/op7418/Youtube-clipper-skill) — Content Control repurposing.
3. [openshorts](https://github.com/mutonby/openshorts) — Content Control repurposing.
4. [claude-seo](https://github.com/AgricIDaniel/claude-seo) — Money Factory acquisition and website audits.
5. [toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) — Content Control story and asset planning.
6. [ruflo](https://github.com/ruvnet/ruflo) — Money Factory orchestration and memory.
7. [youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent) — Content Control YouTube planning and analytics.

All seven sources were fetched and pinned as Git submodules. This is source integration, not a claim that their services, models, skills, or MCP servers are installed, deployed, or producing verified output. Per-repository runtime blockers are recorded in the registry.

Preserve the existing Content Control/Remotion engine, character board, voice assignments, QA, and Money Factory business contracts. Use these additions through adapters; do not replace working components. Keep publication disabled. Do not activate paid providers without approval. Operations must remain phone-friendly; do not require a desktop.

URL query parameters supplied with the request were intentionally discarded. Never persist those tokens in configuration or project memory.

On resume, read the registry and bridge, initialize the pinned submodules, and configure/test each integration in the recorded order. Update runtime status only with actual execution evidence. This file is durable repository memory; it does not claim to modify ChatGPT's personal memory.

## Runtime integration follow-up

Six repositories now have verified local operations through `integrations/run.py`: clipping and burned captions; OpenShorts CPU vertical reframing and transcript windows; Claude SEO HTML parsing; Toonflow workspace brief import; Ruflo native SQLite store/read-back; AgentTube discoverability audit. The eight-operation smoke suite and three negative checks pass. AgentTube's upstream suite passed 47/47 after native SQLite repair. Toonflow web/server builds passed using direct package builds. See `integrations/local-verification.json` for operation-specific receipts.

Content Control calls the same worker through `scripts/repository_tools.py`; no duplicate vendor copy is needed. Its read-only `/api/integrations/status` endpoint does not claim hosted readiness from local tests.

Outstanding: Wan needs a CUDA host and model weights. Hosted worker setup, model/provider connections, MCP registration, and full end-to-end production remain unverified. On 2026-10-13, Chris confirmed the CC email account: use Render `My Workspace` under cyzorcreations@gmail.com, workspace ID `tea-darsafojo6nc739844hg`. This selection is authorized; do not request the same confirmation again. The primary existing service is `content-control-render-worker` (`srv-darsdb8u01pc73dn4i2g`), on the free plan. A live check of `/api/integrations/status` returned HTTP 503 with `WORKER_NOT_CONFIGURED`, `production_ready: false`, `publication_enabled: false`, and `paid_generation_enabled: false`. Account confirmation does not resolve the missing hosted worker or Wan GPU/model requirements. Do not label the overall system 100% ready.

## 2026-10-13: hosted CPU execution verified

The earlier `WORKER_NOT_CONFIGURED` observation is superseded. Render's existing CC service now uses `REPOSITORY_WORKER_BACKEND=github-actions`, and reads the latest public workflow plus operation-specific receipts. No paid resources were provisioned.

Money Factory workflow run 38364409610 (source `ace974bb9da15de97afdde9d77da78b3f574a1c7`) passed all eight CPU operations through Content Control's pinned bridge, plus three safety checks. See `integrations/hosted-verification.json`. Clipper produced decoded clips and burned captions; OpenShorts produced 1080×1920 video with audio and transcript windows; Claude SEO parsed HTML; Toonflow imported and read back a workspace brief; Ruflo wrote/read native SQLite; AgentTube audited content. The upstream AgentTube suite also passed 47/47. Fixed Bun changing Toonflow's tracked CLI executable permission; the source-integrity check remains enforced.

`repository-job.yml` is available for reviewed public-repository jobs through GitHub's existing authorization. Run 38364409636 processed the existing Amex-vs-Chase draft metadata/dialogue; its output hash was verified and saved in `integrations/results/amex-vs-chase-audit.json` and its receipt. The audit executed successfully but reported two advisory findings, not creative approval: brand salience and comparison intent. Do not blindly rewrite the fictional entertainment script to satisfy generic SEO rules.

Remaining limits: Wan has no provisioned CUDA/model backend. CPU hosted jobs are ephemeral; they do not provide persistent Toonflow projects or Ruflo service state. Full model/provider-driven generation, semantic clip selection, authenticated SEO services, and orchestration remain unverified. No MCP clients were registered. Hosted verification is limited to named operations and does not establish every upstream product feature or full production readiness. Publication and paid generation remain disabled. Public repository job inputs must never contain private media or credentials.
