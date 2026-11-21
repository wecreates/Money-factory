# One-command unpublished production bundle

The standalone artifact command reuses Content Control's existing Episode1 producer, then runs the existing OpenTimelineIO exporter and the shared portable delivery packager. It preserves the approved narration and existing voices. It does not publish, alter canonical files, approve creative quality, or bypass the durable queue's capacity policy.

## Prerequisites

Use a clean, reviewed Content Control checkout and its exact commit/source-manifest pins. Install its pinned transcription and picture requirements in an isolated Python 3.11+ environment, run `npm ci --ignore-scripts` in that checkout, and cache the public `Systran/faster-whisper-base.en` model before offline production. FFmpeg/FFprobe, Cairo, Node and the caption font must be available. Use the existing runtime doctor to verify these prerequisites; it does not certify host capacity.

Install the hash-locked OTIO runtime from `integrations/opentimelineio/requirements.lock`. Optional DNSMOS uses the existing pinned requirements and separately downloaded, identity-verified local model described in [its README](../dnsmos/README.md). No model download, provider client or package install happens during this production command.

```sh
python -m integrations.content_control.runtime_doctor \
  --content-control-root /absolute/content-control --describe-only \
  --expected-commit REVIEWED_CONTENT_CONTROL_COMMIT
```

Copy the resulting `source_manifest_sha256` from the reviewed clean checkout. Run:

```sh
python -m integrations.content_control.produce_review_bundle \
  --output /absolute/new-production-run \
  --content-control-root /absolute/content-control \
  --source-commit REVIEWED_CONTENT_CONTROL_COMMIT \
  --source-manifest-sha256 REVIEWED_SOURCE_MANIFEST_SHA256 \
  --video-python /absolute/transcription-runtime/bin/python \
  --picture-python /absolute/picture-runtime/bin/python \
  --otio-python /absolute/otio-runtime/bin/python \
  --timeout 900
```

To request isolated-narration diagnostics, add both `--dnsmos-python /absolute/dnsmos-runtime/bin/python` and `--dnsmos-model /absolute/sig_bak_ovr.onnx`. The command converts only the source-bound isolated narration to 16kHz mono PCM16; it never scores the musical mix as isolated speech. `DIAGNOSTIC_COMPLETE` is inference completion, with no quality approval threshold. An unavailable optional diagnostic is recorded as `BLOCKED`, independently of completed production and interchange. Omitted diagnostics are `SKIPPED`. Exhausting the overall production budget still blocks the bundle.

## Outputs and exact scope

- `review/`: original producer outputs, full technical/audio/ASR receipts and review notes.
- `edit/`: native OTIO export retaining the exact 18 cuts, original continuous mixed audio, and caption markers. This is trimmed rendered media, not recovered artwork, editable burned captions or separated stems.
- `diagnostics/`, when requested: source-bound converted narration and diagnostic report.
- `delivery/review/index.html`: local playback page, video and receipts; captions are already burned in. Local caption-track support varies by browser.
- `delivery/review-package.zip`: portable complete delivery with one MP4 copy, relative timeline/media references and a file-hash manifest.
- `bundle.json`: source/tool identities, stage results, diagnostic scope and delivery identity. Successful engineering completion is `AWAITING_REVIEW`; full audiovisual/creative review remains pending.

The shared `review_package.package_review` function also powers [verified queue result delivery](video-queue.md). Queue callers first validate durable successful-job evidence. Standalone callers verify the clean source, runtime prerequisites and completed producer receipts. Both generate the same delivery format.

## Execution ownership

Linux/WSL2 is required. The command takes the same cross-adapter admission lock to serialize work and gives every external stage a two-CPU kernel affinity and an owned-process guardian. All stages and prerequisite probes share a 30–1800-second deadline. Guardians retain the lease until their children exit. Source checks run before and after production; copied artifacts are rehashed. The output must be new, and packaging refuses symlink ancestors, nested output directories, reserved names and changed source files. Failure preserves production logs without labeling a partial result complete.

This is an explicitly requested standalone artifact run. It does **not** claim the durable queue's host-budget admission, a memory limit, user-PC/VPN installation, 24/7 operation, browser playback, NLE import, or creative acceptance. The queue continues to refuse unknown or insufficient cgroup budgets. CPU affinity is an enforced CPU constraint; RAM still requires appropriate host planning. Publishing, paid generation and production approval remain disabled.

## Executed production evidence

[Fresh execution receipt](production-bundle-proof-20261121.json): **2026-11-21 15:00:41–15:01:17 UTC**, 35 seconds, clean Content Control `7a1caa4c6ffdc241681b2c69664c74e737784bd3` and exact 22-file manifest `7c28f2b84f8133093a61486396fa06f6f0b8f29880a5cd7d01895abbf8db78d4`. Every existing producer stage completed, including fresh narration and encoded-MP4 ASR, source/retention, captions, render, full decode, mobile and technical audio checks. OTIO roundtrip preserved 18 cuts/720 frames at 24fps and nine caption markers; DNSMOS completed on isolated source narration, with no quality acceptance threshold. ZIP and copied file hashes were independently checked; exactly one MP4 is included.

New candidate: `509e5bf5627ccbe3b7b867d1390e8d82b0112f686076767290ee236920af633c`. This hash differs from earlier picture cuts and inherits none of their sampled or creative reviews. Browser playback and full audiovisual acceptance are separate observations; the execution receipt initially records playback unverified. The actual successful hosted queue delivery proof is a different candidate and is documented separately.
