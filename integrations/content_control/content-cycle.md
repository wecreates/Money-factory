# Fresh content production and revision cycle

This opt-in route connects a new researched editorial brief to the existing Money Factory queue, Content Control's pinned free voice generator, fresh picture-video rendering, encoded speech checks, three thumbnail choices, and portable review delivery. It does not overwrite the existing Episode 1/Remotion route or its voices.

## Input and editorial scope

Start with `examples/rewards-card-brief.json`. A brief contains HTTPS source links, retrieval timestamps, short supporting excerpts, explicitly typed reference observations, and original scene writing with claim-to-source IDs. `compile_editorial` validates structure and binds these inputs; it **does not fetch the URLs, invent research, or automatically write the scenes**. This example was researched and written with connected tools. The workflow reel is a transcript observation, while Oddsofmind is only an unobserved user preference. Neither is labeled an audiovisual comparison.

Supply 1–30 scenes, supported voice names (`dave`, `points_monk`, `narrator`), and typed card/receipt/balance/checklist/comparison visual specifications. Arbitrary prose directions are retained for editorial review but are not interpreted as generated artwork or full character animation. Planning durations are replaced with measured speech durations. Maximum rendered duration is ten minutes. New projects should provide fresh source observations; no scheduled discovery is enabled here.

## Runtime and production

Use Python 3.11+, FFmpeg/FFprobe, DejaVu Sans Bold, and `requirements-cycle.txt`. Reuse the isolated pinned Kokoro runtime and verified model cache described by Content Control's voice runtime. Voice assignments stay Dave `am_fenrir`, Points Monk `am_michael`, narrator `am_adam`. The trusted `--voice-root` points to the reviewed Content Control checkout containing `scripts/v2_free_voice.py`; job data cannot supply executables or runtime paths. Models and packages are provisioned separately; production is offline and free of paid provider calls.

For verified captions, supply the existing isolated faster-whisper runtime. Base.en must already be cached under `~/.cache/huggingface`, or set `CYZOR_ASR_HF_HOME` to its cache. Set `HF_HOME` to the separate Kokoro cache. Omitting ASR produces explicitly approximate captions and cannot establish spoken-word verification.

```sh
HF_HOME=/absolute/kokoro-cache python -m integrations.content_control.complete_cycle \
  --brief /absolute/new-brief.json --output /absolute/new-attempt \
  --voice-python /absolute/kokoro-runtime/bin/python \
  --voice-root /absolute/reviewed-content-control \
  --transcription-python /absolute/transcription-runtime/bin/python \
  --timeout 900
```

This standalone command creates an explicit artifact attempt; it does not certify host capacity. For shared-worker operation use the existing queue adapter below. Every attempt uses a new directory. Failure remains `BLOCKED`, records its stage/reason, and preserves diagnostics. Success is `AWAITING_REVIEW`, never creative approval.

Outputs include the exact brief/editorial, fresh narration stems, original diagram panels, measured scene timeline, MP4, captions, speech-verification receipt, three PNG thumbnail candidates, local review HTML, portable ZIP and bound receipts. Thumbnail variants are frame-derived choices, not measured CTR winners. The webpage exposes reference scope and outstanding review requirements. No posting or publishing APIs exist in this path.

## Existing durable queue

The adapter name is `content-control-cycle`. Its exact request fields are:

```json
{
  "operation": "produce-content-cycle",
  "brief": {},
  "brief_sha256": "SHA256_OF_CANONICAL_BRIEF_JSON",
  "timeout_seconds": 900,
  "publication_enabled": false,
  "paid_generation_enabled": false
}
```

Replace the brief with a full valid object; compute its hash with `integrations.content_control.cycle_job.brief_digest`. The existing `integrations.local_agent_queue` accepts host-only `--cycle-voice-python`, `--cycle-voice-root` and optional `--cycle-transcription-python` settings. Its owned-process guardian, two-CPU affinity, shared admission lock, fresh memory/CPU admission, SQLite attempts/retries and artifact checking remain in force. Unknown capacity blocks admission; there is no bypass. Successful queue execution verifies the candidate, source brief, editorial, render receipt, captions, package files and ZIP identities before recording technical success.

This registers an operation, not an always-on daemon. A tested PC/VPN/VPS worker and persistent service supervision are separate deployment requirements.

## Review, feedback and revision

A technical pass does not imply good storytelling, factual correctness, natural voice delivery or competitor parity. Record evidence for the exact candidate using `cycle_review`:

The installed REA Video analyzer can first collect separate, candidate-bound
diagnostics through this same review entry point:

```sh
REA_VIDEO_MODELS=/absolute/cached-rea-models python -m integrations.content_control.cycle_review \
  --cycle-dir /absolute/attempt --analyze \
  --rea-runtime /absolute/rea-video/.venv/bin/python --output /absolute/new-analysis
```

This checks the completed cycle before and after analysis and preserves the
original review package. It uses the pinned installed analyzer and cached face
model, with OCR enabled and provider inference, ASR, stem separation and downloads
disabled. Scene/OCR diagnostics are neither full audiovisual observation nor a
review attestation. Inspect the generated evidence before recording judgments.
See [the analyzer adapter](../rea_video/README.md) for runtime and evidence scope.

```sh
python -m integrations.content_control.cycle_review \
  --cycle-dir /absolute/attempt --review /absolute/reviewer-observations.json \
  --output /absolute/new-recorded-review.json
```

Review JSON contains `candidate_sha256`, `reviewer`, timezone-bearing `reviewed_at`, and a `checks` object. Each check has boolean `passed` and concrete `evidence`: `factual_accuracy`, `full_audiovisual`, `voice_naturalness`, `visual_readability`, `originality`, `reference_comparison`. Missing or failed checks yield `REVISION_REQUIRED`; all complete checks yield `EDITORIAL_REVIEW_RECORDED`, explicitly an attestation, never independent verification or publishing approval. Do not mark listening/watching complete from transcription or still frames.

To feed an edited brief back into production:

```sh
python -m integrations.content_control.cycle_review \
  --cycle-dir /absolute/attempt --review /absolute/new-recorded-review.json \
  --revision-brief /absolute/edited-brief.json --output /absolute/new-revision-input
```

The resulting `brief.json` is directly runnable, with separate provenance linking its superseded candidate, review and source evidence. Changed media cannot reuse an old review. Existing sources/reference observations are retained. Each revision gets fresh narration/render/caption/thumbnail checks and a new candidate identity.

## Verification boundaries

Publishing, paid generation, production approval and full audiovisual approval remain false. A source ID is provenance, not an entailment proof. ASR checks speech consistency, not factual or creative correctness. Fixture tests use explicitly synthetic audio; only separately recorded actual runtime receipts demonstrate Kokoro/ASR execution. All-day autonomous topic discovery, script authorship, live competitor audiovisual access, audience-performance learning and target-host supervision are not supplied by this command.

### Record a thumbnail/title choice

After inspecting the three packaged thumbnail PNGs, record an editorial choice
without changing the immutable delivery package:

```bash
python -m integrations.content_control.cycle_selection \
  --cycle-dir /absolute/path/to/completed-cycle \
  --selection /absolute/path/to/selection.json \
  --output /absolute/path/to/new-selection-receipt.json
```

The input requires `candidate_sha256`, `package_sha256`, `thumbnail` (one of
`thumbnail-1.png` through `thumbnail-3.png`), `thumbnail_sha256`, the exact packaged
`title`, `reviewer`, timezone-qualified `reviewed_at`, and `rationale`. Changing
the title requires a new package because it is embedded in the thumbnails.
Optional `next_idea_hypotheses` retains up to ten reviewer suggestions; these are
not automatically consumed by ideation yet.

Omit `performance` or set it to null when analytics are unavailable. The receipt
keeps impressions, clicks and CTR null, never invented zero values. Optional
supplied performance must bind the same candidate/title/thumbnail and provide
integer impressions/clicks, `window_start`, `window_end`, `observed_at`,
`source_url` and `evidence`; it remains explicitly unverified, even when CTR can
be calculated. A selection never grants creative or publishing approval.

[The November 21 selection receipt](cycle-selection-proof-20261121.json) records
visual inspection of the actual unpublished candidate's three PNGs and selection
of variant 1. No audience metrics, full audiovisual approval or phone playback
acceptance was available. C08 remains open for a real learning consumer and
available verified performance evidence.
