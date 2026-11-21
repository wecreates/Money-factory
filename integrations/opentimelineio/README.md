# Editable timeline handoff

Export a completed Content Control `produce_episode1_review.py` review directory into a portable native OpenTimelineIO timeline. This complements the existing Remotion/OpenMontage production tools: it neither renders nor changes the canonical candidate.

This is a **trimmed rendered-media edit**: 18 cuts reference one existing MP4, with one continuous original mixed-audio track and timed caption markers. Captions remain burned into the picture. The exporter does **not** recover source artwork, separate music/narration/SFX stems, or editable text layers. Actual NLE import/playback is not yet verified; when importing, use the Audio track once and do not also enable audio from the Video clips.

## Pinned free runtime

Upstream: [AcademySoftwareFoundation/OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO), [v0.18.1](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/releases/tag/v0.18.1), commit `44236713c1db295a6ffc66189ae98dbdfd0cb9c4`. The release is labeled beta; its README describes the API as stable. Apache-2.0 license and upstream NOTICE are retained here. The pinned README supports Python 3.9–3.12; this adapter uses Python **3.11+**, tested on 3.12.14. Native Linux wheels avoid a local C++ build. No model, API key, paid provider, GPU, optional OTIO plugins or GUI is needed. FFprobe must be on PATH.

Use an isolated environment:

```sh
python3.12 -m venv /path/to/otio-runtime
/path/to/otio-runtime/bin/python -m pip install --require-hashes --only-binary=:all: -r integrations/opentimelineio/requirements.lock
```

One export command, using the SHA256 of the trusted producer's `run.json`:

```sh
/path/to/otio-runtime/bin/python -m integrations.opentimelineio.export_review \
  --review-dir /path/to/completed-review \
  --run-sha256 RECORDED_RUN_JSON_SHA256 \
  --output /path/to/new-edit-package
```

The output contains `timeline.otio`, one byte-identical copy of `video.mp4`, `captions.vtt`, the original run/render receipts, and `export-receipt.json`. All media references use relative filenames; move the complete directory together. Source media are never modified. The small single copied MP4 makes this package portable without requiring the whole source repository. Existing outputs and symlinked inputs are rejected. On export failure, only the newly created output directory is removed.

Validation binds the exact caller-supplied run hash to the copied video, caption and renderer receipt hashes, checks 18 contiguous integer cuts totaling 720 frames, and probes actual 24fps/30-second video and continuous audio. Native OTIO serialization is read back and checked for exact shot ranges, media hashes, audio duration and caption text/millisecond timing. The expected run hash is an identity pin, **not an authorization signature**. Other historical QA files referenced by the original run are not copied or re-executed. This operation verifies only interchange and does not promote original technical evidence into creative acceptance.

## Executed evidence

[Actual picture roundtrip](actual-picture-roundtrip-20261121.json), **2026-11-21 01:50:11 UTC**: real previously generated candidate `79bbf8abe422e6ff1ef8ee0e2224a952a3114ac435c6b49a8154725ee4dc0053`; 18 cuts, 720 frames at 24fps, nine caption markers, H264/AAC, all package hashes bound. The original producer run was `AWAITING_REVIEW`; publication and production approval remain false. This is a workspace runtime result, not installation on the user's PC or an NLE acceptance result.

Run focused tests with:

```sh
/path/to/otio-runtime/bin/python -m unittest integrations.opentimelineio.test_export_review -v
```

Tests create a real small H264/AAC fixture, round-trip through the actual OTIO runtime, move the package and resolve each relative reference. Negative cases cover tampering, invalid cuts/cues, missing/true approval flags, bad media, symlinks, output collisions, copy failure cleanup, and altered serialized timing/caption text. Synthetic fixture tests do not claim creative quality.
