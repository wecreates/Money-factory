# Queued unpublished Episode1 video jobs

The durable local queue can invoke Content Control's existing
`produce_episode1_review.py`. It reuses the approved Episode1 audio/artwork,
fresh speech recognition, strict captions, renderer and technical checks.
It does not generate new approved scripts, synthesize paid voices, promote a
candidate, deploy or publish. A successful queue job means a verified local
review packet exists; `review_status` remains `AWAITING_REVIEW`, and
`full_av_review`, `production_approved` and `production_ready` remain false.

Prepare a job using a clean, operator-selected Content Control checkout that
includes the owned-stage runner API (PR1218 or later). The runtime doctor reports
the exact source commit and canonical SHA-256 manifest of its 22 input files.
Copy those observed values into the immutable request; do not invent them:

```json
{
  "id": "episode1-review-001",
  "adapter": "content-control-video",
  "request": {
    "operation": "produce-episode1-review",
    "source_commit": "OBSERVED_40_HEX_COMMIT",
    "source_manifest_sha256": "OBSERVED_64_HEX_MANIFEST",
    "timeout_seconds": 900,
    "publication_enabled": false,
    "paid_generation_enabled": false
  },
  "max_attempts": 2,
  "publication_enabled": false,
  "paid_generation_enabled": false
}
```

The doctor checks installed prerequisites without inference. The queue checks
source identity again immediately before execution and after production. Source
changes require a newly reviewed job with a new identity; retries retain the
original immutable source pin. Runtime paths belong to the operator, never the
job document. Python venv interpreter paths are preserved rather than resolved
to their base interpreter.

```sh
python -m integrations.local_agent_queue --queue /local/queue enqueue /local/video-job.json
python -m integrations.local_agent_queue --queue /local/queue work \
  --content-control-root /local/content-control \
  --video-python /local/asr-venv/bin/python \
  --picture-python /local/picture-venv/bin/python
python -m integrations.local_agent_queue --queue /local/queue status --id episode1-review-001
```

The single consumer creates `attempts/JOB_ID/NUMBER/review/` with video, captions,
stage logs and hash-bound receipts. Files and directory entries are flushed
before the adapter returns success for the SQLite transaction. The outer
`video-adapter-receipt.json` binds the pipeline receipt and exact candidate.
The queue directory must be on operator-owned durable local storage; scratch
execution is not proof of production-host persistence or backups.

This adapter currently requires Linux or WSL2. Each stage inherits a kernel
affinity limit of two observed allowed CPUs. The existing shared host admission
lock serializes it with local text adapters. Admission reserves two execution
cores and 1536 MiB incremental memory in addition to the existing OS reserve.
Memory is a planning estimate, not an enforced address-space limit. Unknown
CPU/container memory limits block execution; installing prerequisites does not
override that gate. The production deadline is 30–1800 seconds; prerequisite
checks have their own short subprocess timeouts. No model is downloaded during
production; the existing base.en cache must already be present.

Each external stage uses the existing parent-death guardian and retains a copy
of the shared admission lease until its worker group is killed and reaped.
Killing the consumer cannot silently free the budget while its FFmpeg/ASR stage
continues. On restart, an unfinished durable claim becomes `interrupted` and is
not replayed. A complete-looking raw video does not convert that unknown outcome
into success. Inspect its receipts, explicitly retry if appropriate, and retain
the earlier attempt. Re-enqueuing an already completed identical job does not
render again. These are queue dispatch guarantees, not exactly-once rendering
across a crash or a claim of unattended 24/7 service.

## Retrieve a private playable review package

After the worker completes, use the immutable job ID to check delivery readiness:

```sh
python -m integrations.content_control.review_delivery --queue /local/queue --id episode1-review-001 status
python -m integrations.content_control.review_delivery --queue /local/queue --id episode1-review-001 export --output /local/new-private-review
```

Open `new-private-review/review/index.html` or the adjacent `video.mp4` in a
local video player. The ZIP is the same portable package used by the standalone
producer. It contains the original video bytes, caption timing, producer evidence
and source/job hashes. No server starts and no file is uploaded. Browser codec
and local-file playback support must be observed; package creation alone does
not prove playback. Captions are burned into the picture; the VTT remains
available as text/timing rather than relying on a browser's local caption track.

The delivery command reads SQLite without creating or migrating it. It requires
the latest attempt to have durable success and rechecks the immutable request,
adapter receipt, producer receipt, source manifest and every artifact hash.
Interrupted, blocked, failed, missing or changed results cannot be exported, even
when an MP4 exists. Output must be a new directory; originals and all previous
attempts remain unchanged. A blocked status exits with code 2 and explains the
next action. Resolve its cause and use the queue's explicit `retry` only after
reviewing the retained attempt; status/export never retries or renders.

`delivery_ready=true` means identity-verified technical completion only. The
package remains `AWAITING_REVIEW`; full audiovisual/creative acceptance,
production readiness and publishing approval remain false.
