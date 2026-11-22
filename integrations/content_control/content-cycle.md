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

Pass that handoff explicitly to production to retain its lineage in the new
cycle (neighboring files are never auto-detected):

```sh
python -m integrations.content_control.complete_cycle \
  --brief /absolute/new-revision-input/brief.json \
  --revision /absolute/new-revision-input/revision.json \
  --output /absolute/new-revised-cycle \
  --voice-python /absolute/kokoro-runtime/bin/python \
  --voice-root /absolute/reviewed-content-control \
  --transcription-python /absolute/transcription-runtime/bin/python
```

The supplied revision must bind the exact brief bytes and keep every approval
and feedback-resolution flag false. Its exact text and SHA-256 are embedded in
`cycle.json`; review inspection, queue completion checks and checkpoint recovery
validate that binding. Mutation during production blocks the attempt. The
embedded handoff survives checkpoint restoration without the original workspace.
It records asserted parent/review identities, not independent authentication of
the parent or reviewer, and does not verify feedback resolution. Standalone
production still accepts ordinary briefs without a handoff. Queue requests retain
their existing brief-only interface; they do not yet submit revision handoffs.

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

### Character motion in picture scenes

Each scene now uses a bounded three-second arm gesture loop: 24 deterministic
panels sampled at 8 fps and encoded at 24 fps. Typography, diagrams, character
faces and labels stay fixed; fixed-length arms rotate subtly around the
shoulders. The representative `panel-XX.png` remains the zero-phase image.
Render receipts retain loop settings and every source frame hash alongside each
encoded scene hash. Frame generation observes the same render deadline and
FFmpeg remains under the existing owned-process/resource controls.

This is limited procedural gesture animation, not lip synchronization or full
interpretation of arbitrary scene directions. Existing voice assignments and
publication/creative-review gates are unchanged. New media requires a new
selection and full audiovisual review; old candidate approvals do not transfer.

The [November 21 actual motion-cycle receipt](cycle-motion-proof-20261121.json)
records a fresh six-scene, 34.585-second Kokoro/ASR run completed at 19:23:13 UTC.
The candidate changed; all full audiovisual, listening, reference-comparison and
phone-playback gates remain open.

### Resume review after workspace loss

The delivery `review-package.zip` is a viewing bundle. It does not contain the
root brief, cycle receipt and original render layout needed by `inspect_cycle`.
For future production, add `--checkpoint /absolute/new-cycle-checkpoint.zip` to
`complete_cycle`. After technical success, this creates a separate recoverable
snapshot without changing the completed cycle. A backup failure returns exit 2
and a `checkpoint.status` of `BLOCKED` while preserving the completed media.

Keep the checkpoint ZIP and its returned SHA-256 in durable storage, with the
expected hash retained separately from the archive. A local checkpoint alone is
not durable delivery. Restoration must target a new directory and requires that
external expected hash; it validates the archive and then runs the existing
exact-cycle inspection before exposing the restored directory. This resumes
review/revision and selection, not model installations, raw voice stems or
long-running workers. It cannot reconstruct missing metadata from older
viewing-only ZIPs or transfer an old review to changed media.

```bash
python -m integrations.content_control.cycle_checkpoint create \
  --cycle-dir /absolute/completed-cycle --output /absolute/new-checkpoint.zip
python -m integrations.content_control.cycle_checkpoint restore \
  --archive /absolute/checkpoint.zip --expected-sha256 SHA256_FROM_CREATE_RECEIPT \
  --output /absolute/new-restored-cycle
```

Checkpoint round-trip tests use explicitly synthetic media; they establish
recovery and corruption-handling behavior, not actual production-media approval.

Atomic restore currently supports Linux (`renameat2` with no-replace) and Windows;
unsupported platforms fail closed. A destination created by another process
while validation runs is never replaced. Keep the returned checkpoint hash
outside the ZIP; restore does not treat an archive's own manifest as external
proof of its identity.

Actual recovery was verified on November 21 using the retained motion video's
saved package and exact hash-matching metadata recovered from repository evidence.
The new checkpoint was saved, retrieved into a separate directory, restored and
checked against every original source hash. A new thumbnail-selection record
was made for the motion candidate. See
[the recovery receipt](cycle-recovery-proof-20261121.json) for its external archive
hash, durable version identity and limits. This recovered review state; it did
not reprovision Kokoro/ASR runtimes or grant audiovisual/phone acceptance.

For recreating missing free voice/ASR environments, use the tested
[free runtime setup](free-runtime-setup.md). Fresh caption verification now
requires the exact four-file ASR snapshot and records its verified identity;
mutable cached model names cannot silently select a different model.

## Fresh minimum-payment episode (2026-11-21)

The agent selected a new topic, read current CFPB sources, wrote the original
script/storyboard, and applied an independent source-review correction before
running the existing free production command. See
[research and authorship](examples/minimum-payment-research.md),
[reusable brief](examples/minimum-payment-brief.json), and
[actual run and durable checkpoint](minimum-payment-proof-20261121.json).

The 35.919-second candidate has ASR-verified speech/caption text correspondence and remains
`AWAITING_REVIEW`. This is partial C02 evidence: the production CLI still consumes
a supplied brief; no unattended discovery service or complete watch/listen and
creative revision acceptance is established. Publishing and paid generation remain
disabled. Issue #543 remains the sole completion checklist.

## Caption media-end validation (2026-11-21)

Observed ASR word timestamps are now bounded by freshly probed encoded container
duration, rather than padded decoded audio duration. A word ending beyond that
bound fails before caption replacement; no timestamp is silently clamped. The
transcription receipt retains `duration_seconds` for decoded ASR compatibility and
adds `encoded_media_duration_seconds` for the actual caption bound.

[Actual replay evidence](caption-bound-proof-20261121.json) verifies the existing
minimum-payment candidate still passes with byte-identical captions. The original
cycle was not modified. This closes a validation gap, not full timing, listening,
or creative acceptance; cross-sentence caption grouping remains a separate review
issue.

## Sentence and pause caption grouping (2026-11-21)

Observed captions now break after recognized terminal punctuation and pauses of
at least 0.5 seconds, retaining the seven-token cap and original word timestamps.
Common English abbreviation/initial exceptions avoid some false sentence breaks;
this is a heuristic, not guaranteed sentence or scene segmentation. Zero-duration
tokens can join a positive cue; invalid zero-duration cues still fail closed.

[Actual production evidence](sentence-caption-proof-20261121.json) retains before/after
caption text and the saved checkpoint for a fresh same-brief candidate. The
previous package is untouched. The observed cross-sentence bridges are removed,
but playback/readability/listening and full creative acceptance remain open.

## Diagram-focused thumbnails (2026-11-21)

Known 720x1280 picture-renderer outputs now use the declared diagram crop
`[45, 300, 675, 870]` when building the right-hand thumbnail inset. This enlarges
diagram labels while retaining the title. Unknown media retains full-frame
containment. Each thumbnail records framing, source dimensions, crop and exact
frame timestamp; the preview identifies cropped variants.

[Actual repackaging evidence](thumbnail-focus-proof-20261121.json) retains new
package/thumbnail hashes and a saved viewing ZIP. Video, captions, voices and
original cycle remain unchanged. This ZIP is a viewing package, not a replacement
for the earlier exact-cycle recovery checkpoint. Previous package selections
are not transferred. Visual readability review does not establish CTR, mobile
playback, full audiovisual or creative acceptance.
