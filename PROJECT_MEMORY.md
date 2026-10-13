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

## 2026-10-13: durable reviewed results and live browser execution

Reviewed public JSON/text job results now persist in Git under `integrations/results/runs/<run-id>-<attempt>/` after a separate runner checks source-job and output hashes, upstream pins, and disabled-publication flags. Audit runs 38366476053 and 38366867768 passed processing and recording on fresh runners. Media remains a temporary artifact; this does not provide private database persistence.

Claude SEO's real Playwright Chromium renderer successfully fetched the public CYZOR homepage in a mobile viewport through Content Control (run 38366868376, source ae664c3cb2c0bf3e29dd75cfc8bd2b062f3957e9). HTTP 200, rendered mode, no reported console errors, 6202 characters of extracted text. A separate runner verified and committed the result and receipt. HTML fields are explicitly truncated at 50000 characters; this is browser execution evidence, not a complete SEO certification. The website job is reusable and restricted to public CYZOR HTTPS URLs without credentials or query parameters.

Remaining blockers are unchanged: Wan CUDA/model backend, private persistent Toonflow/Ruflo state, provider/OAuth connections and complete model-driven workflows. Publication and paid generation remain disabled. Do not claim 100% production readiness.

## 2026-10-13: Wan optional by user decision

Chris authorized skipping Wan and completing the existing Remotion production path. Wan remains pinned for optional future use, disabled and not required for production. Do not provision GPU services or count Wan as a current release blocker. This does not waive voice, sound, captions, visual-style, character, factual, or mobile-playback QA. Latest inspected Content Control V2 record (run 38372639017) passes six technical/audio checks but remains blocked on verified reference provenance and exact-candidate aligned-frame style comparison. No finished-video or publication approval is implied.

## 2026-10-13: operational visual analysis and comparison

Four additional agents repaired and independently reviewed the visual-analysis path. Content Control now separates completed visual measurements (`analysis_status: COMPLETE`) from artistic acceptance. The actual V2 draft (SHA-256 `8d8b0559f8f0b49dd5875e4c81e19d9005c15933faf22adce10968ef3169743b`) was fully decoded: 839 frames at 24 fps, 34.96 seconds. Timestamped reference/candidate contact sheets, full-frame motion metrics, independent frame findings, and real OpenCLIP/Florence CPU comparison are saved under `state/visual-analysis/` in Content Control. 26 Python and 8 creative-handoff tests passed. Hosted deterministic visual-analysis run 38432656338 passed.

The independent inspection identified smaller/thinner captions, smaller characters and sparse staging relative to the ten reference images. White backgrounds remain intentional brand direction. These findings are not artistic approval. Existing reference images lack verified source-video provenance and therefore cannot establish competitor motion or audio parity. New source-video intake records exact frame/source hashes; no provenance was invented.

The dedicated visual-analysis workflow runs on relevant changes and hourly. Semantic analysis follows completed V2 builds and runs daily; each run writes fresh artifacts separate from historical snapshots. Both paths keep publication disabled and do not bypass full audiovisual/creative approval. Wan remains optional and disabled.

Hosted semantic run 38432656326 completed successfully with real model inference and fresh video-derived frames; artifact digest `14f723be59f01d4d0d07d0a36f42cdbfe1daff446c7ccca8965d4ef842d99774`. The legacy always-blocked visual gate is repaired: an exact-artifact documented static-frame review can now PASS or FAIL, while invalid or incomplete evidence remains BLOCKED. Current inspected draft correctly FAILS on observed mismatches; this is successful analyzer operation, not a finished-video approval. Full audiovisual and competitor review remain required before customer handoff.

Final hosted visual-analysis run 38433915515 passed after integrating the documented-review gate. Software execution is verified; the current video's artistic verdict remains FAIL.

## 2026-10-13: rendered visual repair follow-through

Content Control source `6810581ff756dd20d96d03631527f4c82fb20ef9` increases captions to 70–72px bold rendering, enlarges actors while preserving contact coordinates, anchors the moving cape to Goblin's hand, and clears cards/captions and sword/card labels. 25 focused tests pass. Hosted run 38452208211 generated the actual 839-frame, 24fps draft; all six technical/audio/caption checks passed. Exact candidate SHA-256: `e8fd5b0b51930c662d89a8d4ad2348b0b81f414bf51ffa0e637afc0618b6d2d8`.

The final 67 observed caption cues were measured in Chromium with the production font and wrapping; zero clipped glyphs. A 1,001-sample sword geometry sweep found zero corrected card-label intersections. The complete video decoded successfully, and independent inspection of ten actual frames confirmed cape contact and caption/card clearance. Exact-candidate visual analysis completed with an honest FAIL decision: expressive headline styling, close framing and varied scene context still need work; board consistency, real-phone playback and full audiovisual approval remain unverified. The hosted build correctly blocked its older review hash; the subsequent saved review binds to the new exact candidate and does not grant approval.

Evidence is committed in Content Control `e15dd941d65c1227cfa33c75690c8451af8c8ce0`: `state/visual-analysis/repair-2026-10-13/` (comparison images, all-frame motion, build record and verification), `repair-evidence/` (caption and sword geometry receipts/reproduction inputs), and the current `frame-review.json`. Historical semantic results retain their own hashes; do not relabel them as this video's results. Publishing and customer handoff remain disabled. Wan stays optional/disabled. No claim of 100% production readiness.

## 2026-10-13: technical and sampled visual blockers repaired; all six repository operations verified

Content Control source `e9fb2d8711f0b3a3aca5787ebcf06e367382aadd`, build 38473857671, produced exact candidate `896006c7af0571fa98f2f17e22aafa7030a424c9c47f2f85d130c7173f181edf`. New expressive observed captions, closer paired framing and distinct arena/lounge/checkpoint/victory settings repair prior visual findings. A finish-only enlargement hid the sandwich in intermediate candidate a80cf3ae; that candidate was rejected and the extra enlargement removed. Five full-resolution ending samples verify the corrected visible sandwich. No rejected review was reused.

All eight technical checks PASS: voices, mix, transcription, captions, caption-frame coverage, technical video, shared character-renderer binding and phone-sized Chromium playback. Actual video is 840 frames at24fps/35.0s; container35.041s, pre-mux caption lattice841. All68 observed cues and71 words remain visible in the actual frame lattice. All204 caption geometry samples pass. 38 focused Node tests and17 Python evidence/reconciliation tests pass. These facts do not certify listening quality or physical Android hardware.

Independent15-frame review PASS across typography, character scale, staging, sampled board consistency and360px raster readability. Reconciliation38475379030 succeeded; live V2 state is REVIEW_REQUIRED with all nine checks PASS, not BLOCKED on a stale review. Original build failure/outcome and receipt hashes are preserved. Visual analysis38475378861 succeeded. Fresh semantic run38474835714 completed actual OpenCLIP and Florence CPU inference on this same candidate; ZIP digest and12 decoded frame hashes verified. Similarity metrics are diagnostics, not creative approval. Evidence: Content Control commits ea3ba0fde03d692f0b97bd0d68b73b1dba21682b and bc53f0d1121e9e632aa9e96935bbfe826d715d53, folder `state/visual-analysis/completion-2026-10-13/`.

Final hosted handoff38474835778 executed eight operations across all six non-Wan repositories against this exact candidate, using existing pinned adapters: Youtube-clipper clip and caption burn; OpenShorts vertical export and observed transcript windows; claude-seo metadata HTML parsing; youtube-automation-agent content audit; Toonflow brief import with actual JSON read-back; Ruflo native canonical project-memory rehydration. Every operation receipt and output hash independently verified. Artifact11854090952 SHA256 de2b7fabc675f07d609a1c7322febee9fa2e551527542c03f74393ca8f1ab05e. Compact inputs/results/receipts are durable in the evidence folder. Audit execution PASS still returns two editorial advisories (intro branding and comparison intent); do not conflate execution success with content approval.

Limits remain explicit: sampled frames and automated metrics do not establish full audiovisual or competitor motion/audio approval. Stored reference stills lack independently verified source-video linkage. Full upstream provider/OAuth/model workflows remain unverified; tested scope is the named free CPU operations. Ruflo rehydrates PROJECT_MEMORY.md from pinned Money Factory d8a7038 in ephemeral SQLite; no persistent database or current-video native memory claim. This Git-backed note is the durable current project memory. Derived teasers are not final approved edits. Publishing and customer handoff stay OFF. Wan remains optional/disabled by Chris's instruction. Do not claim100% production readiness.
