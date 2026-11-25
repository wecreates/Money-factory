# Fresh content production and revision cycle

This opt-in route connects a new researched editorial brief to the existing Money Factory queue, Content Control's pinned free voice generator, fresh picture-video rendering, encoded speech checks, three thumbnail choices, and portable review delivery. It does not overwrite the existing Episode 1/Remotion route or its voices.

`python -m integrations.content_control.cycle_discovery --pool /absolute/candidate-pool.json --output /absolute/selection` is an optional offline prerequisite for unattended research. It selects among two or more externally observed, sourced topic candidates using conservatively normalized source-domain coverage, every declared source/reference timestamp, and a stable ID tie-break. Pool selection is limited to 24 hours after `created_at`; every evidence timestamp must fall within the prior 30 days and cannot postdate the pool. Hostnames are normalized offline using lowercase IDNA and a deliberately bounded suffix rule so subdomains cannot inflate independence. It writes `research.json` for the existing intake and a replayable `discovery.json` receipt containing the policy, exact pool/research hashes and selected candidate. The command does not fetch sources, measure popularity, fact-check claims, or establish competitor quality; those remain separate agent/runtime and acceptance evidence. Use `--verify /absolute/selection` to replay the decision without writing files.

`python -m integrations.content_control.cycle_authoring --pool /absolute/candidate-pool.json --research /absolute/selection/research.json --discovery-receipt /absolute/selection/discovery.json --output /absolute/draft.json` can turn that exact verified selection into a deterministic offline first script/storyboard draft. It preserves the narrator → Dave → Points Monk → narrator assignments, produces authored stick-figure visual specifications, and embeds the pool/research/receipt and script/storyboard identities. Intake replays the algorithm byte for byte and rejects edited or substituted drafts. This is a free, model-free authored prerequisite only: `authorship_verified`, originality review, factual review, competitor comparison, audiovisual review, approval, paid generation and publication all remain false.

Add `--format long-form` to produce a source-bound landscape manuscript and
storyboard with at least eight scenes and at least 120 seconds of planning
duration. The long-form receipt binds the complete repeated narrator/Dave/
Points Monk speaker sequence, exact planned duration and a distinct replay
algorithm. Intake and the durable queue replay it byte for byte. This only
opens the existing renderer's greater-than-60-second path; planning duration is
not measured media duration, and `long_form_production_verified`, authorship,
originality, factual, creative, listening, competitor, phone, deployment and
publication acceptance all remain false until separately evidenced.

Long-form authoring version 2 recognizes the exact retained utilization source
set (`fico_utilization`, `experian_reporting`, and `cfpb_grace_period`) only
when all three sources are in canonical order, carry their canonical HTTPS
hosts and paths without credentials, ports, query strings, or fragments, and
retain the normalized bounded claim/excerpt text specific to the formula,
reporting timeline, and grace-period definition. IDs alone, reordered or
duplicate sources, wrong hosts/paths, and unrelated prose fall back to generic
source-bound authoring or fail at the existing discovery boundary; they cannot
activate the hard-coded utilization facts. The verified source set then
builds a topic-specific closing-date story instead of the generic two-source
shell. It includes a complete hook/title, visible utilization arithmetic, a
statement-close/reporting timeline, source-name cards, a no-score-promise
boundary, and varied authored gestures while retaining the same narrator,
Dave, and Points Monk voices. The reporting-source narration deliberately uses
its role while the on-screen card displays `EXPERIAN`; raw independent ASR
captions therefore are not rewritten from expected text to correct a guessed
proper noun. Retained version-1 long-form drafts continue to replay under their
original algorithm. This is still deterministic first-draft production, not
factual, originality, listening, creative, or audiovisual acceptance.

To assemble those three prerequisites and the exact durable-queue envelope in
one fail-closed step, without manually supplying a script, run:

```sh
python -m integrations.content_control.cycle_offline_handoff \
  --pool /absolute/candidate-pool.json \
  --output /absolute/fresh-offline-handoff \
  --job-id content-cycle-001 --format long-form
```

The fresh output retains the exact external pool, selected research, discovery
receipt, deterministic script/storyboard, verified intake, and a validated
`queue-job.json`. It does **not** enqueue or execute that job. Recheck the saved
bytes without changing them using `--verify /absolute/fresh-offline-handoff`.
The pool is still externally observed: this handoff performs no live research,
retrieval, trend measurement, originality check, factual review, creative or
audiovisual review, production, competitor acceptance, deployment, publishing,
or paid inference. Those flags remain false in both the manifest and request.

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

Rebuild and verify the exact saved brief and receipt without modifying them:

```sh
python -m integrations.content_control.cycle_intake \
  --research /absolute/research.json --draft /absolute/draft.json \
  --verify /absolute/existing-intake
```

The verification result identifies the four retained byte sets. Supply the
same prior selection paths described below if the intake used idea learning.

To require this verification as part of standalone production, use the intake
directory's original `brief.json` as `--brief` and add `--intake-research` and
`--intake-draft` with the original inputs. If the intake used idea learning,
also add `--intake-prior-cycle`, `--intake-selection`, and
`--intake-selection-receipt` with the original paths. If that learning is
bound to a later audience observation, also add
`--intake-audience-observation` and `--intake-audience-receipt` with those
original paths. Production checks
the saved brief and receipt before rendering and rechecks the intake before
success. The cycle receipt keeps `verified_intake`, including the original
research, draft, brief and intake receipt hashes. Production from a supplied
brief and queued production keep their existing options. Verified intake establishes byte
provenance, while source discovery, factual checking and authorship still
require separate evidence.

To carry a prior thumbnail review into the next draft, add an `idea_learning`
object to the draft with `selection_receipt_sha256`, a one-based
`hypothesis_index`, and an `application` describing the change to test.
Supply the original private review cycle, its submitted selection JSON, and its
separate recorded selection receipt:

```sh
python -m integrations.content_control.cycle_intake \
  --research /absolute/research.json --draft /absolute/draft.json \
  --prior-cycle /absolute/prior-cycle --selection /absolute/submitted-selection.json \
  --selection-receipt /absolute/recorded-selection.json --output /absolute/new-intake
```

Intake revalidates the prior package, reconstructs the selection from the
submitted JSON, and binds the requested hypothesis and next-draft application
into the brief and intake receipt. Production carries them into the compiled
editorial and delivery. A revision preserves this origin. Keep those three
private selection inputs with the new intake for replay. The handoff records
the rationale for an editorial experiment. It carries no counts or CTR and
supplied audience data remains unverified.

To bind a later, separately recorded audience observation to that experiment,
add the exact `audience_receipt_sha256` to `idea_learning` and supply the
original observation and audience receipt in addition to the three selection
inputs:

```sh
python -m integrations.content_control.cycle_intake \
  --research /absolute/research.json --draft /absolute/draft.json \
  --prior-cycle /absolute/prior-cycle --selection /absolute/submitted-selection.json \
  --selection-receipt /absolute/recorded-selection.json \
  --audience-observation /absolute/audience-observation.json \
  --audience-receipt /absolute/recorded-audience.json --output /absolute/new-intake
```

Intake replays both receipts and requires their selection, package, title and
thumbnail identities to agree. It can carry forward only one hypothesis that
was already written in the prior selection. The new handoff retains the exact
selection, observation and audience-receipt hashes and the
`SUPPLIED_UNVERIFIED` status. It deliberately omits counts, CTR, evidence and
source fields, does not choose a winner, and does not promote the observation
to verified performance. Standalone production rejects an audience-bound brief
unless all original intake and audience paths are supplied for replay. Queue
requests reject audience-bound learning until the queue has an equally bounded
inline contract for the original selection and audience evidence; legacy
selection-only learning remains supported.

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

Each newly generated isolated narration clip receives deterministic level matching to
0.075 RMS, capped at 1.9× gain and 0.95 peak. This closes the measured shortfall
of the retained Points Monk clips without changing its assigned voice. Version-1
receipts with the previous 1.8× ceiling remain strictly replayable, while mixed
algorithm/ceiling claims fail closed. `voice.json` retains the source
level, applied gain, resulting level and an explicit false listening flag. This
reduces voice-to-voice level jumps; it is not loudness, naturalness,
pronunciation or full-mix acceptance. The exact finished candidate must still
pass the direct full-mix listener review below.

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

The source-pinned Episode 1 producer also gets this diagnostic when launched
through the Money Factory `content-control-video` queue adapter or the
standalone review-bundle command. The report runs under the existing process
guardian and deadline, stays beside the original producer packet, and is
verified again when copied into the private ZIP. Older completed attempts
without a report remain exportable. Direct Content Control production runs
outside these wrappers are separate.

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

After permitted live playback, record two full audiovisual observations against
the exact unpublished candidate with:

```bash
python -m integrations.content_control.cycle_live_comparison \
  --cycle-dir /absolute/completed-cycle \
  --observations /absolute/live-comparison.json \
  --output /absolute/new-comparison-receipt.json
```

Replay a retained source and receipt against the unchanged cycle without
writing a new receipt:

```bash
python -m integrations.content_control.cycle_live_comparison \
  --cycle-dir /absolute/completed-cycle \
  --observations /absolute/live-comparison.json \
  --verify-receipt /absolute/new-comparison-receipt.json
```

The input names the exact candidate SHA, reviewer and review time, one complete
candidate observation, schema version 2, and exactly two distinct competitor references. Candidate
and reference observations are contiguous intervals from zero through the full
declared playback duration. Every interval records audio, visuals, pacing and
story observations. Each reference also carries explicit audio, visual, pacing
and story differences from the candidate plus at least one actionable finding;
generic observation text alone is insufficient. Each reference carries its
topic/format, selection basis, a separate dated ranking-evidence URL, and dated playback evidence. Its
access record must explicitly say `live_view_only`, playback permitted, media
not downloaded, accessible, picture accessible and sound accessible. A specific
Instagram reel URL is accepted only under those live-view conditions; the
command never opens or downloads it. Missing picture or sound, partial interval
coverage, duplicate references, inaccessible playback, a candidate mismatch or
missing separate ranking evidence fails closed.

The resulting `COMPARISON_ATTESTATION_RECORDED` receipt binds the exact candidate,
cycle/package identities, normalized observations and submitted observation
bytes. It deliberately keeps
`independent_verification`, `competitor_comparison_verified`, `full_av_review`,
production approval/readiness, publication and paid generation false. Schema
validation proves neither that playback happened nor that a competitor is truly
high-performing; those claims still require independently supported runtime and
creative acceptance evidence.

### Listen locally with an audio-input model

The optional loopback listener can scan a verified mono candidate without a
hosted render or inference service. Start a trusted audio-capable llama.cpp server on
`127.0.0.1` with matching local weights and projector. With LFM3-Omni-2B, use
`--reasoning off`. Keep the server private. Then record findings:

```sh
python -m integrations.content_control.cycle_local_audio_listener \
  --video video.mp4 --video-sha256 "$video_sha256" \
  --caption captions.vtt --caption-sha256 "$caption_sha256" \
  --model LFM3-Omni-2B-Q4_K_M --port 8791 --output audio-observations.jsonl
```

The command binds the exact video and captions, measures the program duration,
and sends contiguous 12-second audio windows with neighboring context to the
loopback model. It retains observations plus flags for truncated or missing
response fields. A complete receipt records local model coverage. The model
name identifies the requested model and is supplied by the caller. Use known
audio controls and an independent listener before treating a model finding as
a production decision, especially for character identity and subtle masking.

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
For a renderer-declared 24 fps comparison reveal, the gallery also retains the
adjacent decoded pictures immediately before and at the planned reveal frame.
The receipt records their actual playback timestamps and hashes so the reviewer
can inspect the transition directly. Still images leave listening and continuous
motion review open.
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

For a fresh research intake, add optional `intake_input` with exactly these
fields:

- `research_json` and `draft_json`: exact UTF-8 text of the original inputs.
- `receipt_json`: exact UTF-8 text of the generated `intake.json`.

For research produced by `cycle_discovery`, also supply both
`discovery_pool_json` and `discovery_receipt_json` as the exact UTF-8 pool and
receipt bytes. A brief carrying `topic_discovery` is rejected by both direct
production and the queue unless those bytes are supplied through verified
intake. The queue replays the selection, requires an exact match to
`research_json`, retains all five inputs in the private attempt, and carries the
selected candidate, pool/research/receipt hashes, domain policy, freshness
policy and complete recency score through the brief, intake proof, cycle receipt
and durable delivery verification. Omitting either discovery field is rejected.

Supply the generated `brief.json` as the decoded `brief` object and keep its
canonical `brief_sha256`. Read the three text inputs with
`Path.read_bytes().decode('utf-8')` to preserve their original line endings.
The queue rebuilds the original brief bytes, verifies the receipt, and retains
the inputs inside the private attempt. Completion and private export recheck
the same inputs and expose their identities in `verified_intake`. Each text
input is limited to 128 KiB. The existing 150,000-byte serialized queue job
limit still applies to the entire envelope. Intakes requiring a prior selection
and its original review package use the standalone path. Use `revision_input`
separately for a revision. The intake receipt verifies retained bytes.
Source retrieval, factual accuracy, authorship, and creative review remain
separate evidence.

Inspect or export a durable successful attempt from an existing queue:

```sh
python -m integrations.content_control.review_delivery --queue /local/queue --id cycle-review-01 status
python -m integrations.content_control.review_delivery --queue /local/queue --id cycle-review-01 export --output /local/new-private-review
python -m integrations.content_control.review_delivery verify \
  --output /local/new-private-review \
  --expected-delivery-identity <trusted-delivery_identity_sha256>
```

The read-only command verifies SQLite completion against the adapter receipt,
exact production brief, revision lineage, and packaged candidate. On Linux or
WSL2 it atomically creates a separate directory containing the original
`review-package.zip`, an immediately openable `review/index.html` tree and a
root `package.json`. The root receipt binds the durable job digest and attempt,
exact candidate, source package, archive, entrypoint and every copied preview
file in one `delivery_identity_sha256`. Interrupted or changed attempts cannot
be exported. The preview remains private and unpublished; this identity proves
copied bytes, not browser/device playback, creative approval or durable off-host
storage. The queue-independent `verify` command requires the expected delivery
identity from a separate trusted handoff, reopens the retained directory,
rehashes its exact preview tree and original ZIP members, and recomputes the
delivery identity, including its complete cycle provenance, without rewriting
either source. A self-contained directory proves only internal consistency: all
contained hashes could be coherently replaced. A PASS means the external
identity matched the retained bytes. It does not prove phone/browser playback,
which still requires an observed device session.

### Deliver an exact retained checkpoint through the queue

To deliver previously completed bytes without running synthesis again, enqueue
a `content-control-retained-cycle` job. Its request contains exactly
`operation: restore-unpublished-cycle`, `publication_enabled: false`,
`paid_generation_enabled: false`, an integer `timeout_seconds` of 5–300, and
these SHA-256 pins from a trusted prior handoff:

| Request field | Exact bytes |
| --- | --- |
| `checkpoint_sha256` | Checkpoint ZIP |
| `candidate_sha256` | `delivery/video.mp4` |
| `caption_sha256` | `delivery/captions.vtt` |
| `brief_sha256` | `brief.json` |
| `pipeline_receipt_sha256` | `cycle.json` |
| `package_sha256` | `delivery/package.json` |
| `archive_sha256` | `delivery/review-package.zip` |

Supply the archive path to the worker on Linux or WSL2, outside the job request.
Run one job at a time with its corresponding checkpoint.

```sh
python -m integrations.local_agent_queue --queue /local/queue enqueue /local/retained-job.json
python -m integrations.local_agent_queue --queue /local/queue work \
  --cycle-checkpoint-path /local/checkpoint.zip
```

The guarded worker retains its own checkpoint copy, verifies and restores the
cycle, and flushes the attempt files before recording success in SQLite. Its
deadline covers the restore child, including file copies and flushes. Delivery
rechecks the checkpoint, restored files and durable receipt. Use the same
`review_delivery` commands above for an unpublished export, or use the queue
Short consumer below with a retained portrait cycle as its input. The queue
directory and output remain local, with device playback and creative review
still pending.

### Queue a fresh render from a revised brief

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

To attach the retained detector evidence to a submitted review, add
`--rea-analysis /absolute/new-analysis/analysis.json` when recording it.
The review command rehashes the accompanying `diagnostics/` directory, compares
the detector summary to the exact bound render, and requires the diagnostics to
finish between the completed cycle and the review date. It retains the receipt
identity, detector status, and authored-cut coverage in the recorded review.
When a detector miss caused the analyzer to build authored-scene navigation,
the review also replays the complete scene receipt and every gallery/frame hash.
Each missed authored cut becomes an exact scene/time diagnostic action in the
recorded review and revision handoff: a human must inspect that transition and
rerender only if audiovisual review confirms a defect. Missing-cut detection is
not itself a creative verdict. Altered or fully blocked results cannot be
attached. Existing review calls remain valid without this option. Runtime
execution, full motion/audio judgments and publication approval still require
their own evidence.

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
  --live-comparison-source /absolute/live-comparison.json \
  --live-comparison-receipt /absolute/new-comparison-receipt.json \
  --output /absolute/new-recorded-review.json
```

Review JSON contains `candidate_sha256`, `reviewer`, timezone-bearing `reviewed_at`, and a `checks` object. Each check has boolean `passed` and concrete `evidence`: `factual_accuracy`, `full_audiovisual`, `voice_naturalness`, `visual_readability`, `originality`, `reference_comparison`. A supplied `full_audiovisual` judgment also requires `watcher_review`: the exact candidate and captions, a named watcher and time, `basis: direct_full_audiovisual_watch_and_listen`, contiguous coverage from zero through the bound rendered duration, and all five granular checks (`picture_continuity`, `caption_readability`, `audio_visual_sync`, `pacing_and_transitions`, `creative_coherence`). Its pass/fail result must agree with the summary check. A supplied `voice_naturalness` judgment also requires `listener_review`: the exact candidate, a named listener and time, `basis: direct_full_mix_listening`, the same complete-duration coverage, and all six granular checks (`naturalness`, `pronunciation`, `character_consistency`, `music_and_sfx`, `transitions`, `mix_balance`). A supplied `reference_comparison` judgment requires the retained raw comparison source and exact `COMPARISON_ATTESTATION_RECORDED` file through the two explicit CLI options above. The recorder re-hashes both files, replays the receipt's candidate, cycle and normalized-observation identities, then retains both verified hashes in the review. A later revision replays the embedded normalized receipt and carries those already-verified file identities; it does not claim to re-read absent raw source bytes. Free-form comparison text alone is insufficient. The recorder replays the bound `render/voice.json` receipt and canonical Dave / Points Monk / narrator assignments. Checkpoints retain those small receipts, not voice models, raw stems or competitor media. ASR, transcripts, signal measurements and sampled frames are rejected as watching or listening bases. Missing or failed checks yield `REVISION_REQUIRED`; all complete checks yield `EDITORIAL_REVIEW_RECORDED`, explicitly an attestation, never independent verification or publishing approval. Do not mark listening/watching complete from transcription or still frames.

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
without changing the immutable delivery package.

New packages compare the fitted frame artwork before applying accent colors
and title copy. When a nominal frame repeats earlier artwork, the packager
tries up to four alternate timestamps from the same video. The receipt records
the original sampling time if replaced, or identifies which variant repeats
when no distinct sampled artwork is available. This is a pixel-identity
comparison within the candidate, with visual choice and audience response
reviewed separately.

```bash
python -m integrations.content_control.cycle_selection \
  --cycle-dir /absolute/path/to/completed-cycle \
  --selection /absolute/path/to/selection.json \
  --output /absolute/path/to/new-selection-receipt.json
```

New inputs use `schema_version: 2` and require `candidate_sha256`,
`package_sha256`, `thumbnail` (one of
`thumbnail-1.png` through `thumbnail-3.png`), `thumbnail_sha256`, the exact packaged
`title`, `reviewer`, timezone-qualified `reviewed_at`, and `rationale`.
An optional `thumbnail_copy` in a new or revised editorial brief prints separate
overlay text on all three images while leaving the episode title intact. It
accepts 1–48 printable characters on one line after normalizing spaces. Without
it the thumbnails still print the title. The package and recorded selection
retain supplied overlay text. If the selection also asserts `thumbnail_copy`,
it must match the existing image copy. Changing the title or copy requires a
new package, with its own selection and evidence.
Optional `next_idea_hypotheses` retains up to ten reviewer suggestions. A
separate draft can explicitly carry one forward using the intake option above.

Omit `performance` or set it to null when analytics are unavailable. The receipt
keeps impressions, clicks and CTR null, never invented zero values. Optional
supplied performance must use the exact documented fields, bind the same
candidate/package/title/thumbnail filename and SHA-256, and provide
integer impressions/clicks, `window_start`, `window_end`, `observed_at`,
`source_url` and `evidence`. The receipt timestamp must be at or after the
observation, and its window must not begin before `reviewed_at`. Do not supply
unknown outer selection fields or `ctr`, winner, verification, status, or audience
conclusion fields: CTR is derived from the submitted counts, while every such
packet remains explicitly unverified and inadmissible to performance-informed
learning. A selection never grants creative or publishing approval.
Schema-version-1 selection receipts and the immediately preceding version-1
readiness layout remain replayable from their retained original inputs, but all
newly recorded selection and learning-readiness receipts use schema version 2.

When counts become available only after the editorial selection was recorded,
retain them as a separate exact-selection observation:

```bash
python -m integrations.content_control.cycle_audience \
  --cycle-dir /absolute/path/to/completed-cycle \
  --selection /absolute/path/to/submitted-selection.json \
  --selection-receipt /absolute/path/to/recorded-selection.json \
  --observation /absolute/path/to/audience-observation.json \
  --output /absolute/path/to/new-audience-receipt.json
```

The observation supplies the exact selection-receipt, candidate, package,
thumbnail and title identities plus integer impressions/clicks, a chronological
window, observation timestamp, credential-free HTTPS evidence link and evidence
note. Re-run the command with `--verify-receipt` instead of `--output` to
reconstruct a retained receipt from all four original inputs. These receipts are
always `SUPPLIED_UNVERIFIED`: the command does not log in to analytics, infer a
winner, or certify audience performance. A later intake can bind the exact
receipt to one already recorded reviewer hypothesis as described above, but it
does not copy metrics or treat the hypothesis as a measured winner. Keep the
original selection input, selection receipt and observation for replay.

[The November 21 selection receipt](cycle-selection-proof-20261121.json) records
visual inspection of the actual unpublished candidate's three PNGs and selection
of variant 1. No audience metrics, full audiovisual approval or phone playback
acceptance was available. C08 still requires available verified performance
evidence and its use in subsequent ideation.

Use the learning-readiness gate before treating any retained selection or later
audience receipt as performance evidence:

```bash
python -m integrations.content_control.cycle_learning_readiness \
  --cycle-dir /absolute/prior-cycle \
  --selection /absolute/submitted-selection.json \
  --selection-receipt /absolute/recorded-selection.json \
  --hypothesis-index 1 --output /absolute/learning-readiness.json
```

Add `--audience-observation` and `--audience-receipt` together to assess a later
observation. Current receipts are `UNAVAILABLE` or `SUPPLIED_UNVERIFIED`, so the
gate intentionally returns `BLOCKED` (exit code 2) while preserving the exact
selection, package, thumbnail, hypothesis, and optional audience identities. It
also retains the selected thumbnail filename and explicitly records that
performance values were not admitted. It does not copy counts or CTR into an
automated decision. Re-run with
`--verify-receipt` instead of `--output` to replay a retained result. A future
trusted read-only analytics adapter must bind the exact package and observation
window before performance-informed learning can become ready; this command does
not authenticate an account or convert submitted metrics into verified data.

### Character motion in picture scenes

Each scene now uses a bounded three-second arm gesture loop: 24 deterministic
panels sampled at 8 fps and encoded at 24 fps. Typography, diagrams, character
faces and labels stay fixed; fixed-length arms rotate subtly around the
shoulders. The representative `panel-XX.png` remains the zero-phase image.
Add `gesture` to a scene's `visual_spec` to direct the existing motion.
`point_left` and `point_right` move one arm toward that side of the image,
while `open_hands` moves both arms. Omit the field to retain the existing pose
sequence. The render receipt records any explicit direction with the scene's
frame hashes. Gestures loop independently of narration and timed reveals.
Set `speaker_label_position` to `above` in a portrait brief (or intake draft)
to put the printed name between the diagram and the character. This leaves the
lower caption area clear of speaker names. Diagram thumbnails use a tighter
crop for that layout so the moved name stays outside the artwork. Omit the
field to preserve the existing layout. Review readability on the final player.
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
The parent span and planned portrait duration must be at most 60 seconds.
Production checks the portable handoff's scene order and evidence identities.
It also checks the bound narration's frame budget before drawing and verifies
the encoded picture and container lengths before transcription and delivery.
The queue remeasures the picture and container lengths from the bound MP4 and
checks them against the producer receipts and 60-second maximum. A mismatched
or overlength delivery fails review and export. Retained packets without a
maximum-duration claim remain readable.
Measure the actual export separately. No cropping or reuse of a landscape
audio stream occurs in this path.

The bounded `cycle_short` consumer extracts an explicitly selected interval from
an already validated cycle without generating new speech or changing voices:

```sh
python -m integrations.content_control.cycle_short \
  --cycle-dir /absolute/completed-cycle --output /absolute/new-short \
  --start 0 --end 30 --timeout 180
```

When the parent came from the durable local queue, consume it by immutable job
ID instead of supplying an artifact path:

```sh
python -m integrations.content_control.cycle_queue_short \
  --queue-root /absolute/queue --job-id JOB_ID \
  --output /absolute/new-short --start 0 --end 30 --timeout 180
```

To bind the cut to authored scene boundaries already recorded in the durable
parent render receipt, supply one or more contiguous scene IDs instead of time
bounds:

```sh
python -m integrations.content_control.cycle_queue_short \
  --queue-root /absolute/queue --job-id JOB_ID \
  --output /absolute/new-short \
  --scene opening --scene worked-example --timeout 180
```

Scene IDs must exist, be unique, and appear contiguously in authored order. The
consumer derives the exact start and end from the package-bound render receipt,
canonicalizes both to the exporter's millisecond timebase, then replays that
selection during verification. This proves the cut matches the exportable form
of those authored scene boundaries; it does not prove they are the best
editorial selection or confer creative approval.

This read-only queue consumer requires a durably succeeded `content-control-cycle`
or `content-control-retained-cycle` attempt. It replays the SQLite job and
attempt, adapter receipt, cycle/package/archive identities and, when applicable,
the retained intake or checkpoint evidence before and after the existing Short
exporter runs. `queue-short.json` binds the
job digest and attempt to the parent candidate/cycle, exact Short MP4 and VTT,
encoded H.264/AAC packet hashes and an ordered decoded RGB-frame hash. The
consumer has a separate read-only verifier and never changes queue state.
These identities prove byte/stream/frame continuity, not picture quality,
listening quality, editorial selection, phone playback or creative acceptance.

The source must already have 9:16 portrait framing and exactly one audio stream;
landscape, rotated or anamorphic inputs fail instead of receiving an invented
crop. The interval must be finite, within source duration and at most 60 seconds.
The consumer re-encodes H.264/AAC, checks decode and dimensions, and independently
limits the encoded picture and container to 60 seconds. If frame rounding
pushes a cut over 60 seconds, the attempt records the measured lengths and stops.
A shorter input interval may fit the source frame cadence. Successful exports
write `video.mp4`, rebased `captions.vtt`, candidate-bound diagnostics and
`short.json`. Open the sibling `index.html` for private review. Its relative
links stay within the excerpt directory, and the receipt records the preview
SHA-256 alongside the exact video, captions, diagnostics and parent identities.
Use the WebVTT track on the sidecar preview and the visible captions on the
burned preview. Both link to the WebVTT text. Keep the files together.
To review a retained candidate offline, generate a single HTML file from its
verified video and caption hashes. The player embeds the original MP4 (up to
32 MiB) and WebVTT with no network access. Open the downloaded HTML in a browser
with local HTML and MP4 playback support. Use the sidecar toggle to check the
separate track and export timestamped playback observations as JSON.

```bash
python -m integrations.content_control.offline_review_player \
  --video video.mp4 --captions captions.vtt \
  --video-sha256 "$video_sha256" --caption-sha256 "$caption_sha256" \
  --output private-review.html
```

Before loading the media, the browser recomputes both embedded SHA-256 values.
It records natural 1x playback only while the page is visible and audio remains
audible; seeking, muting, changing speed, hiding the active tab or a media error
invalidates that pass. A reviewer may reset at time zero and try again. Sidecar
caption coverage is tracked separately.

The exported schema-v2 record retains the machine-observed events, played
intervals, caption state, required reviewer attestations, structured findings,
disposition and optional revision lineage. Its canonical SHA-256 can be replayed
without trusting the browser export:

```bash
python -m integrations.content_control.offline_review_record \
  --record review.json \
  --video-sha256 "$video_sha256" --caption-sha256 "$caption_sha256"
```

Partial or blocked reviews remain exportable as observations. Only a natural
pass plus every explicit reviewer attestation earns the record status
`FULL_REVIEW_RECORDED`. Even then the record keeps independent acceptance,
full audiovisual acceptance, production approval, competitor comparison,
physical-phone verification, publishing and paid generation false. Those gates
require their own evidence. Physical-device playback, listening quality and
creative acceptance still require direct observation.
The exporter validates the source cycle before and after encoding. Fresh output
directories, owned processes, a bounded deadline, two encoder threads and
diagnostic size limits remain mandatory. A failed attempt retains a BLOCKED
receipt without a preview entry point.

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

For an opt-in revision that reserves more room beneath those burned captions,
combine `--compact-captions --caption-safe-area`. The known 720×1280 picture is
scaled to 648×1152, centered horizontally at the top of the same-color canvas,
and burned with the proven `MarginV=29` libass style. The receipt records the
exact transform and a 125-pixel bottom-clearance target. The exporter keeps the
rebased VTT bytes and encoded AAC stream unchanged from the corresponding
compact-caption excerpt. The default and ordinary compact-caption paths remain
unchanged. This deterministic layout target is not a measurement of every font
environment or audiovisual approval; inspect the exact decoded candidate on a
phone before acceptance.

The optional burn requires FFmpeg with libass, DejaVu Sans, and at least one
plain, unmarked cue in the excerpt. Check small-screen readability on the new
file. Visual overlap and timing near cue edges depend on the exact source and
renderer. The receipt covers local technical verification.

Only the pipeline's plain WebVTT is supported. Intersecting cues retain their
whole text while timestamps are clipped to the earliest of the requested,
encoded picture and encoded container ends.
`boundary_cue_numbers` identifies potentially incomplete spoken sentences/words;
review them against the resulting audio. This is not new ASR verification or
automatic editorial selection. Full watch/listen, factual context, caption
accuracy, phone playback and long-form-to-Shorts acceptance remain open, including
when a source already happens to be shorter than a minute. All publishing and
creative approval flags remain false; prior source approval never transfers.

### Record a Short watch/listen review

Generate a blank submission tied to the exact queued Short, sidecar captions,
both Short receipts, presentation mode, measured playback duration and
verified parent voice receipt:

```sh
python -m integrations.content_control.cycle_queue_short_attestation prepare \
  --queue-root /absolute/queue --job-id JOB_ID --short-dir /absolute/short \
  > /absolute/short-observations.json
```

Open the exact Short and watch and listen at normal speed. Fill in the watcher
and listener identities, timezone-bearing observation times, contiguous
`start_seconds` / `end_seconds` intervals from zero through the full measured
duration, and every granular check. Each check needs a boolean `passed` and
concrete evidence. Include playback timestamps in defect notes and optionally
provide repair `feedback` for a failed check. Leave the submission unfinished
if any picture or audio interval was inaccessible.

```sh
python -m integrations.content_control.cycle_queue_short_attestation record \
  --queue-root /absolute/queue --job-id JOB_ID --short-dir /absolute/short \
  --submission /absolute/short-observations.json --output /absolute/short-av-receipt.json
python -m integrations.content_control.cycle_queue_short_attestation verify \
  --queue-root /absolute/queue --job-id JOB_ID --short-dir /absolute/short \
  --receipt /absolute/short-av-receipt.json
```

The receipt replays content and queue identities. A failed check preserves
repair feedback and records `REVISION_REQUIRED`. A clean submission records
`WATCH_LISTEN_ATTESTATION_RECORDED`. The command authenticates the media and the
structure of supplied observations. Independent audiovisual, competitor and
phone verification, production approval, publishing and paid generation stay
outside this receipt.

When that exact receipt has status `REVISION_REQUIRED`, route its failed
watcher/listener checks into the normal Short repair path without retyping or
reclassifying the observations:

```sh
python -m integrations.content_control.cycle_queue_short_review record-attestation-findings \
  --queue-root /absolute/queue --job-id JOB_ID --short-dir /absolute/short \
  --attestation /absolute/short-av-receipt.json \
  --output /absolute/recorded-short-review.json
```

The adapter replays the exact attestation and derivative identities, carries
the original evidence and repair action byte for byte, and maps the granular
check into the existing repair categories. Clean attestations are refused
because they have no repair work to route. The resulting review remains a
repair input only: direct observation, competitor comparison, re-render,
re-review, phone playback and independent acceptance retain their own gates.

### Bind Short repair review and caption revision

A durable queue Short can retain exact repair findings without converting those
findings into audiovisual approval. Submit a JSON object with the exact Short
`candidate_sha256` and `caption_sha256`, the exact `queue_short_sha256`,
`short_receipt_sha256`, and `preview_caption_mode` reviewed, a reviewer and
timezone-bearing `reviewed_at`,
`basis: supplied_repair_findings_not_acceptance`, and one or more `findings`.
Each finding has exact `check`, `evidence`, and `action` fields. The
supported checks are `caption_accuracy`, `caption_readability`,
`voice_and_sound`, `visual_storytelling`, `pacing`, `creative_coherence`,
`reference_comparison`, and `phone_playback`. These are repair notes only; they
do not certify that any check was completed or passed.

```sh
python -m integrations.content_control.cycle_queue_short_review record \
  --queue-root /absolute/queue --job-id JOB_ID \
  --short-dir /absolute/short --review /absolute/repair-findings.json \
  --output /absolute/recorded-short-review.json
```

The recorder replays the durable queue completion and queue Short verifier. The
result binds the exact MP4/VTT, encoded streams, decoded picture, authored scene
selection, parent candidate/cycle, both Short receipts, and submitted review
bytes. Sidecar captions, compact burned captions, and the current safe-area burn
can all receive findings. Its status is always `REVISION_REQUIRED`; audiovisual
acceptance, phone playback, production readiness, publishing, and paid
generation remain false.

For a sidecar-caption Short with a recorded caption finding, prepare a JSON
revision with exact `candidate_sha256`, `caption_sha256`,
`recorded_review_sha256`, `editor`, `rationale`, and `caption_edits`. Caption
edits use the same one-based cue/line and exact before/after contract as the
cycle caption repair command. Fixing captions burned into the picture requires
a new render; the sidecar-only handoff cannot change them.

```sh
python -m integrations.content_control.cycle_queue_short_review revise-captions \
  --queue-root /absolute/queue --job-id JOB_ID \
  --short-dir /absolute/short \
  --recorded-review /absolute/recorded-short-review.json \
  --revision /absolute/caption-revision.json \
  --output /absolute/short-caption-revision
```

The output contains only corrected `captions.vtt` and its immutable revision
handoff. The video and voice identities remain unchanged. This is intentionally
not a consumable revised Short: it must feed a fresh derivative package and
fresh review. A burned-caption Short fails closed because changing its sidecar
alone would leave visible words in the video unchanged.

### Repair captions without regenerating speech

Use a new immutable cycle for an explicit text correction. The original media,
brief, editorial and cue timing bytes stay unchanged; the corrected captions,
render/package receipts and ZIP receive new identities. Supply a JSON object with
exact `candidate_sha256`, `caption_sha256`, `reviewer`, `rationale`, and `edits`.
Each edit has a one-based `cue`, exact full-line `before`, and replacement `after`.
Include a one-based `line` when editing a multiline cue. The source VTT must
use LF line endings and plain cues. Caption text admits the renderer's
`&#x27;` and `&quot;` escapes without changing their bytes. Cue settings,
tags, other entities and bare ampersands are unsupported. Edits must be
bounded, with no controls or duplicates.

```sh
python -m integrations.content_control.cycle_caption_revision \
  --cycle-dir /absolute/old-cycle --edits /absolute/edits.json \
  --output /absolute/new-caption-cycle --timeout 180
```

The new package marks `caption_timing: editorial_text_correction` and sets
`independent_transcription_verified: false`. Original ASR identity is retained
only as prior provenance in the render receipt's `caption_revision`; supplied
edits are retained with their exact input hash. Existing renderer geometry and
scope describe the unchanged source media. The new package requires its own
selection and review.

To merge, split, or reflow adjacent cues, supply `retimed_vtt` (the complete
replacement VTT text) in place of `edits` and run the same command. It requires
identical words and punctuation in order within each contiguous caption
interval. The start and end of each interval and gaps between intervals must
stay fixed. Internal boundaries and line breaks may change. The new package
records `caption_timing: editorial_retiming` and regenerates candidate-bound
diagnostics. Review the new timing against playback. The validation covers
intervals and text; listening and synchronization still require review.


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
