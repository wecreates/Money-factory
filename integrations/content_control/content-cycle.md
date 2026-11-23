# Fresh content production and revision cycle

This opt-in route connects a new researched editorial brief to the existing Money Factory queue, Content Control's pinned free voice generator, fresh picture-video rendering, encoded speech checks, three thumbnail choices, and portable review delivery. It does not overwrite the existing Episode 1/Remotion route or its voices.

## Input and editorial scope

Start with `examples/statement-balance-brief.json`. A brief contains HTTPS source links, retrieval timestamps, short supporting excerpts, explicitly typed reference observations, and original scene writing with claim-to-source IDs. `compile_editorial` validates structure and binds these inputs; it **does not fetch the URLs, invent research, or automatically write the scenes**. This example was researched and written with connected tools. The workflow reel is a transcript observation, while Oddsofmind is only an unobserved user preference. Neither is labeled an audiovisual comparison.

Supply 1–30 scenes, supported voice names (`dave`, `points_monk`, `narrator`), and typed card/receipt/balance/checklist/comparison visual specifications. Arbitrary prose directions are retained for editorial review but are not interpreted as generated artwork or full character animation. Planning durations are replaced with measured speech durations. Maximum rendered duration is ten minutes. New projects should provide fresh source observations; no scheduled discovery is enabled here.

### Separate research and scene drafting

Use the intake command when a researcher supplies sources and a separate
author or local model supplies the title and scenes. Research JSON contains
`schema_version: 1`, `topic`, `sources`, and `reference_observations` in the
existing brief format. Draft JSON contains `schema_version: 1`, the SHA-256 of
the exact research file as `research_sha256`, `title`, and `scenes`. It can also
supply `thumbnail_copy` and `layout`. Drafts cannot add or replace research
records, and factual scenes must cite known source IDs.

```sh
python -m integrations.content_control.cycle_intake \
  --research /absolute/research.json --draft /absolute/draft.json \
  --output /absolute/new-intake
```

Use the resulting `brief.json` with the existing production command. Keep the
two inputs with `intake.json` to verify the byte hashes. The `research_handoff`
in the brief binds both inputs. Intake validates structure and renderer shape.
Source discovery, factual review and authorship are evidenced separately.

Receipt diagrams associate each supplied label with its corresponding value;
comparison diagrams keep labels inside their respective cards, including when
values are omitted. Comparisons support at most two fields; receipt/card layouts
support up to four, and text that cannot fit readable bounds fails explicitly.
Review these associations in the actual rendered frames:
technical encoding success cannot establish that a financial example is visually
unambiguous. The statement-balance example includes the historical $500 balance,
the later +$40 purchase, and the resulting $540 current balance as separate rows.
The [November 22 diagram correction](diagram-pairing-proof-20261122.json) retains
the rejected mixed-code attempt, clean fresh production, caption correction,
checkpoint restoration and independent visual review. Its
[thumbnail selection](statement-thumbnail-selection-20261122.json) is an editorial
choice with performance unavailable, not completion of audiovisual acceptance.

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

### Automatic audio, picture and competitor review

Every new cycle package and exported Short includes `automated-review.json`,
bound to that MP4 and caption file. The picture scan flags black frames and
static intervals. The audio scan measures silence, peak and average level. The
analyst highlights intervals for review. The reviewer handoff calls for a full
watch/listen and checks staging, story, voice, sound and readability. The scans
and ASR cannot certify those subjective checks. Existing review and revision
commands can retain reviewer findings for the exact candidate.

An operator can set `CYZOR_REVIEW_BENCHMARKS` to an absolute local JSON
manifest to compare measured candidate signals with two curated competitors
in the same format. Use references in the candidate's topic and format lane,
with documented evidence for why they are benchmarks. The manifest is
host configuration and cannot be set in a queue job. Use this shape:

```json
{"schema_version":1,"references":[
  {"url":"https://example.org/watch/first","path":"first.mp4","sha256":"64_HEX_CHARACTERS",
   "selection_rationale":"Relevant high-performing peer in this topic and format.",
   "selection_evidence_url":"https://example.org/ranking","selected_at":"2026-11-23T00:00:00Z","authorized":true},
  {"url":"https://example.org/watch/second","path":"second.mp4","sha256":"64_HEX_CHARACTERS",
   "selection_rationale":"Relevant high-performing peer in this topic and format.",
   "selection_evidence_url":"https://example.org/ranking","selected_at":"2026-11-23T00:00:00Z","authorized":true}
]}
```

On a mixed-format worker, replace `references` with `reference_sets`, keyed by
`portrait`, `landscape`, or `square`, and put a two-reference list under each
supported format. A candidate with no matching set stays blocked for comparison.

The comparator reads only authorized files already on disk and makes no network
requests. It records missing, invalid or incompatible evidence as `BLOCKED`.
Selection rationale is retained as operator evidence without ranking or audience
claims being inferred. Instagram remains live-view only. Subjective audiovisual
comparison requires genuine observed playback with audio and is still pending
after the technical comparison. Blocked comparison does not discard a private
candidate or turn on publication or paid inference.

### Native landscape review renders

Set the brief's top-level `layout` to `"landscape"` to render a 1280×720
stage. The existing diagrams appear beside the character, and the same
authored comparison cues apply to the wide layout. The layout is bound to the
editorial, render and package receipts. The authored-scene gallery accepts
this profile and the package generates full-frame thumbnails. Omit the field
for the existing 720×1280 renderer and portrait thumbnail crop.

Portrait excerpts still require an authored portrait source. Landscape is a
layout choice. Duration, listening, device playback and delivery acceptance
remain separate.

For a run with a minimum length, pass `--minimum-duration` in whole seconds
(for example, `--minimum-duration 510` for the 8:30 showrunner target). The
renderer derives a frame budget from the generated WAV lengths and stops before
drawing or encoding if the budget is short. It verifies the encoded picture
stream duration again before transcription. The render receipt retains the
requested minimum and measured values. This check does not infer duration from
the editorial plan or add silence to meet the target.

### Reveal a comparison card during a scene

A `comparison` scene with two complete label/value pairs can opt into
`visual_spec.reveal_after_seconds`. The first card appears from the scene's
first frame. The second appears once at the first 24 fps frame at or after
the supplied scene-local time. It stays visible across the arm-gesture loops.
The renderer records the requested offset and first visible frame in the
scene receipt. The offset must be between 0.25 and 59.5 seconds and leave at
least half a second in the rendered scene. Omit the field for the existing
static comparison. The representative panel shows the complete comparison.

An author can use observed word timestamps to choose the offset. The
renderer does not infer speech alignment. Check the encoded candidate when
the narration, edit or timing changes.

### Review samples from every authored scene

Heuristic shot detection may merge several authored scenes into one representative
image. Export a separate local gallery from the exact completed cycle when a
reviewer needs a frame from each authored scene:

```bash
python -m integrations.content_control.cycle_scene_review \
  --cycle-dir /absolute/path/to/completed-cycle \
  --output /absolute/path/to/new-scene-samples
```

This reads the measured `delivery/render.json` scene intervals, checks their
contiguous order and identity against the bound editorial, and samples each
midpoint from the candidate MP4. Planned storyboard durations are not used.
Actual decoded frame timestamps are recorded and must remain inside the requested
scene; a low-frame-rate source that skips the scene fails with a blocked receipt.
Native PNGs, a contact sheet and a local HTML gallery are linked by a hashed
`scene-review.json` receipt. The source cycle and voices remain unchanged.

Limits are 30 scenes, existing portrait framing, at most 1920×1080 total pixels,
16 MiB per native frame, and a shared 180-second deadline (configurable 10–600).
The existing bounded local media-process runner is reused; no models or network
providers are invoked. Missing/changed source identities or failed decoding do
not produce a successful sampling receipt. Partial outputs remain diagnostic.

This fills an authored-scene **sampling** gap, not full audiovisual review or
independent scene detection. The overview is for navigation; open native frames
for text inspection. External WebVTT captions are not burned into the samples.
Motion, transitions, pacing, listening, reference comparisons and phone playback
still require their own exact-candidate evidence. All publishing, paid-generation
and acceptance flags remain false.

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

Set optional `minimum_duration_seconds` to a whole number from 1 to 600 to
require the same measured picture minimum as the standalone command. The
queue binds it to the immutable request. The worker and private export verify
the matching render and cycle receipts before accepting delivery. Omit it for
the existing duration behavior. It can be combined with `revision_input`.

Inspect or export a durable successful attempt from an existing queue:

```sh
python -m integrations.content_control.review_delivery --queue /local/queue --id cycle-review-01 status
python -m integrations.content_control.review_delivery --queue /local/queue --id cycle-review-01 export --output /local/new-private-review
```

The read-only command verifies SQLite completion against the adapter receipt,
exact production brief, revision lineage, and packaged candidate. On Linux or
WSL2 it atomically creates a separate directory containing the original
`review-package.zip` and a `package.json` receipt that binds queue, candidate,
and archive. Extract the ZIP and open its `index.html`. Interrupted or changed
attempts cannot be exported. Local delivery does not verify device playback or
creative acceptance.

For a revised brief, retain the standard request fields above, including
`brief_sha256` computed from the canonical `brief` object, and add an optional
`revision_input` object with exactly two fields:

- `brief_json`: the exact UTF-8 text of the generated revision `brief.json`.
- `revision_lineage`: the object returned by `cycle_lineage.read_revision` for
  the generated `revision.json` and the SHA-256 of those exact brief bytes.

The raw brief must parse to the same canonical object as the request's `brief`.
Its whitespace is retained because the revision receipt binds the exact bytes,
not a reserialized copy. The adapter writes both inputs inside its owned attempt,
passes their paths through the fixed production command, and rejects a completed
cycle that drops or substitutes the submitted handoff. The adapter receipt keeps
both the canonical request `brief_sha256` and exact `production_brief_sha256`.
Inputs contain data only; executable and runtime paths remain host settings.
The raw brief limit is 256 KiB, handoff 64 KiB, and the existing durable queue's
150,000-byte total serialized job envelope still takes precedence. This does
not authenticate the parent/reviewer or verify that feedback was resolved.

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

Use `--package-lint` for a separate advisory check of the completed cycle's
title and thumbnail copy. It runs the registered, pinned YouTube Agent Skill
locally. The exact candidate, package, tool input and findings are recorded in
a new JSON file outside the cycle. Older packages use the displayed title as
thumbnail copy when there is no authored override.

```sh
python -m integrations.content_control.cycle_review \
  --cycle-dir /absolute/completed-cycle --package-lint \
  --output /absolute/new-package-lint.json
```

Scores and findings cover the shared copy only. Thumbnail image selection,
audience performance and audiovisual approval still require separate evidence.

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
production still accepts ordinary briefs without a handoff. Queue requests optionally carry the same handoff as described above.

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
`title`, `reviewer`, timezone-qualified `reviewed_at`, and `rationale`.
An optional `thumbnail_copy` in a new or revised editorial brief prints separate
overlay text on all three images while leaving the episode title intact. It
accepts 1–48 printable characters on one line after normalizing spaces. Without
it the thumbnails still print the title. The package and recorded selection
retain supplied overlay text. If the selection also asserts `thumbnail_copy`,
it must match the existing image copy. Changing the title or copy requires a
new package, with its own selection and evidence.
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

### Explicit portrait Shorts excerpts

For a completed native landscape cycle, prepare a new portrait brief from
explicit, contiguous authored scene IDs.

```sh
python -m integrations.content_control.cycle_portrait \
  --cycle-dir /absolute/landscape-cycle --output /absolute/new-portrait-handoff \
  --scene opening --scene worked-example --title 'Optional Short title'
```

The handoff verifies the exact source and records its measured scene windows.
It copies the selected scene descriptions, narration, speaker assignments,
visual settings and source citations. Run the new `brief.json` through the
existing production command. The portrait render has newly synthesized audio,
new captions and its own measured duration. Review those exact output bytes.
Both the parent span and planned portrait duration must be at most 60 seconds.
Measure the actual export separately. No cropping or reuse of a landscape
audio stream occurs in this path.

The bounded `cycle_short` consumer extracts an explicitly selected interval from
an already validated cycle without generating new speech or changing voices:

```sh
python -m integrations.content_control.cycle_short \
  --cycle-dir /absolute/completed-cycle --output /absolute/new-short \
  --start 0 --end 30 --timeout 180
```

The source must already have 9:16 portrait framing and exactly one audio stream;
landscape, rotated or anamorphic inputs fail instead of receiving an invented
crop. The interval must be finite, within source duration and at most 60 seconds.
The consumer re-encodes H.264/AAC, checks decode, dimensions and actual duration,
and writes `video.mp4`, rebased `captions.vtt`, and candidate-bound `short.json`.
It validates the source cycle before and after encoding. Fresh output directories,
owned processes, a bounded deadline, two encoder threads and diagnostic size
limits remain mandatory. A failed attempt retains a BLOCKED receipt.

For the known 720×1280 picture renderer only, explicitly add
`--hide-source-counter` to cover its source scene counter in the exported Short.
The receipt records the exact covered rectangle and background color. Unknown
layouts fail closed when this option is requested; the default export remains
unchanged. This is a local presentation edit, not a crop, new narration or
creative approval. The source video and its original numbering remain intact.
The [November 22 counter-removal evidence](short-counter-proof-20261122.json)
records both actual exports, full-frame-count counter-region checks, unchanged
decoded audio and captions, and independent sampled visual review.

For a separate copy with visible captions, add `--compact-captions`. This
applies a small bottom-centered libass style to rebased cues on the known
720×1280 picture layout. The original cycle and normal sidecar-only export are
unchanged. The second pass copies the excerpt's AAC stream and retains a VTT
sidecar for accessibility or editing. Leave the sidecar off during visual
review of the burned copy to avoid displaying the captions twice.

The optional burn requires FFmpeg with libass, DejaVu Sans, and at least one
plain, unmarked cue in the excerpt. Check small-screen readability on the new
file. Visual overlap and timing near cue edges depend on the exact source and
renderer. The receipt covers local technical verification.

Only the pipeline's plain WebVTT is supported. Intersecting cues retain their
whole text while timestamps are clipped to the requested and actual media bounds.
`boundary_cue_numbers` identifies potentially incomplete spoken sentences/words;
review them against the resulting audio. This is not new ASR verification or
automatic editorial selection. Full watch/listen, factual context, caption
accuracy, phone playback and long-form-to-Shorts acceptance remain open, including
when a source already happens to be shorter than a minute. All publishing and
creative approval flags remain false; prior source approval never transfers.

### Correct caption text without regenerating speech

Use a new immutable cycle for an explicit text correction. The original media,
brief, editorial and cue timing bytes stay unchanged; the corrected captions,
render/package receipts and ZIP receive new identities. Supply a JSON object with
exact `candidate_sha256`, `caption_sha256`, `reviewer`, `rationale`, and `edits`.
Each edit has a one-based `cue`, exact full-line `before`, and replacement `after`.
The entire source VTT must use LF line endings and plain single-line cues;
cue settings, tags and entities (including ampersands) are unsupported. Edits
must be bounded, with no controls or duplicates. It never guesses corrections.

```sh
python -m integrations.content_control.cycle_caption_revision \
  --cycle-dir /absolute/old-cycle --edits /absolute/edits.json \
  --output /absolute/new-caption-cycle --timeout 180
```

The new package marks `caption_timing: editorial_text_correction` and sets
`independent_transcription_verified: false`. Original ASR identity is retained
only as prior provenance in the render receipt's `caption_revision`; supplied
edits are retained with their exact input hash. Existing renderer geometry and
scope describe the unchanged source media, not a fresh synthesis run. No old
package selection or approval is transferred. Reinspect the new cycle and create
a fresh checkpoint with the existing commands. This is a text correction based
on supplied reviewer judgment, not listening verification or audiovisual approval.


## Reject unsupported visual fields before production (2026-11-22)

New `complete_cycle` production validates visual field shapes before creating
an attempt or synthesizing voices. Balance diagrams support at most two labels
or two values, and checklists support at most four labels or four values; neither
layout supports both lists together. Comparison supports at most two paired
fields. Use card/receipt for up to four pairs, or comparison for two pairs.
Invalid shapes fail explicitly instead of silently omitting supplied fields.
Direct rendering enforces the same contract.

Historical `compile_editorial` normalization remains unchanged so existing
immutable cycles can still be inspected and restored. New production uses
`validate_visual_shapes=True`; this is a production preflight, not factual or
creative acceptance. The historical rewards-card brief/revision includes both
balance labels and values and is now rejected for new production. Create an
explicit revised brief choosing a supported presentation before rerendering;
do not edit an existing bound cycle. The current statement-balance and
minimum-payment examples remain valid, with identical compiled identities.
