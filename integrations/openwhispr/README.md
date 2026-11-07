# OpenWhispr export bridge

Candidate integration into Money Factory's existing repository worker and Content
Control's existing `scripts/repository_tools.py` bridge. This adapter runs offline,
using Python's standard library. It does not run, install, or activate OpenWhispr.

## Supported operations

- `import-transcript`: read a user-supplied desktop JSON transcript export or
  explicitly selected plain-text dictation/note export. Return a normalized
  transcript and a `capability_queue_record` matching Content Control's existing
  queue record shape. The canonical queue is not overwritten.
- `readiness`: return `BLOCKED / DESKTOP_NOT_VERIFIED` until desktop installation,
  a local model, microphone permission, and a genuine dictation/export round-trip
  are independently verified. A successful file import is not that evidence.

Every job must explicitly set `publication_enabled: false` and
`paid_generation_enabled: false`. Native JSON is the default. For plain text, use
`input_format: "text"` and a nonempty `title` in the job.

From the Money Factory checkout, after applying the central runner wiring:

```sh
python integrations/run.py integrations/openwhispr/fixtures/import-transcript.job.json --runtime /tmp/cyzor-interop-runtime
```

The fixture is synthetic contract data. The output path must not already exist.
For actual use, copy the job to a private local path and point `input` at an
explicitly supplied export. Do not commit private dictation or meeting data into
the public jobs directory. Content Control can invoke the same job through its
existing `MONEY_FACTORY_ROOT` bridge. No new HTTP server or desktop hook is needed
for this file exchange.

## Timing and trust boundaries

The pinned desktop formatter exports `segments[].timestamp`, speaker and text.
It omits segment ends. Its `metadata.duration_seconds` is derived from the last
merged segment's timestamp, not a media probe. The adapter preserves start times
and declared duration separately, invents no ends, and marks caption timing,
audio verification, full audiovisual coverage and production readiness false.
Use actual media alignment before captions/rendering.

Text is untrusted source material. It goes into `source_text`, never into an
executable task command. The queue record remains `pending_editorial_review` and
does not approve facts, production, paid providers or publication. A source hash
makes repeated imports of the same bytes identifiable for review/deduplication.
This is not a transcription-quality evaluation or proof of export authenticity.

## Inspection and activation limits

Inspected revision: `7a6ae826de9ec1caf65f3a6e769475dab2ae829f` (MIT). Exact source
paths, archive hash and file hashes are recorded in `source-inspection.json`.
No upstream code is copied into this adapter or executed by it. The desktop
project's install/start/build hooks compile native key listeners and download
models/helpers; none were run. The security policy identifies native helper,
IPC, credential-storage and supply-chain risks. Local model mode must be chosen
and tested before claiming audio stays local. Optional cloud transcription,
sync, agents and shared notes are separate capabilities requiring review.

The user's MSI computer was offline during preparation. Activation requires the
supported connected-desktop task route, selection of an official stable release,
appropriate install/permission approval, a local model, and an actual end-to-end
dictation/import test. The cloud adapter does not substitute for desktop access.

## Tests

```sh
python -m unittest -v integrations/openwhispr/test_adapter.py
```

Tests cover the pinned JSON shape, plain text, source-data isolation, timing
honesty, deterministic identity, malformed exports, size/symlink/special-file
guards, explicit free-mode flags, and no network/subprocess execution. Input reads
reject parent traversal and symlinks at every ancestor, using descriptor-anchored
no-follow traversal to resist parent-path replacement races. These are
adapter tests, not the upstream Electron application suite or a live MSI test.
