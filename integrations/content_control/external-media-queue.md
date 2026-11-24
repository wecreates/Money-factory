# Queued offline external-media review admission

`content-control-external-media` admits one already-produced, free/offline
OpenMontage safe-reframe packet to the durable queue. It does **not** run
OpenMontage, FFmpeg, Remotion, a model, a provider, a browser, or any network
request. The operator supplies the artifact root on the worker command line;
queued data cannot select a path, command, URL, provider, or runtime.

The immutable request pins all relevant lineage boundaries:

```json
{
  "id": "openmontage-safe-reframe-001",
  "adapter": "content-control-external-media",
  "request": {
    "operation": "package-openmontage-safe-reframe",
    "source_candidate_sha256": "OBSERVED_64_HEX_ORIGINAL_CANDIDATE",
    "transformed_source_sha256": "OBSERVED_64_HEX_TRIMMED_SOURCE",
    "candidate_sha256": "OBSERVED_64_HEX_SAFE_REFRAME",
    "external_receipt_sha256": "OBSERVED_64_HEX_SAFE_REFRAME_RECEIPT",
    "prior_tool_receipt_sha256": "OBSERVED_64_HEX_PRIOR_TOOL_RECEIPT",
    "review_run_sha256": "OBSERVED_64_HEX_REVIEW_RUN",
    "tool_commit": "OBSERVED_40_HEX_OPENMONTAGE_COMMIT",
    "timeout_seconds": 60,
    "publication_enabled": false,
    "paid_generation_enabled": false,
    "production_approved": false,
    "production_ready": false,
    "full_av_review": false
  },
  "max_attempts": 1,
  "publication_enabled": false,
  "paid_generation_enabled": false
}
```

The operator-selected root must contain these regular, non-symlink paths:

- `safe-reframe-receipt.json`
- `diagnostics/prior-openmontage-receipt.json`
- `review/run.json`, `review/video.mp4`, `review/video.mp4.json`, captions, and
  every artifact named by `run.json`

Run one bounded attempt:

```sh
python -m integrations.local_agent_queue --queue /durable/local/queue enqueue /local/job.json
python -m integrations.local_agent_queue --queue /durable/local/queue work \
  --external-media-root /local/reviewed-safe-reframe
python -m integrations.content_control.review_delivery \
  --queue /durable/local/queue --id openmontage-safe-reframe-001 status
```

Before copying, the adapter rehashes the external receipt, prior tool receipt,
review run and candidate and cross-checks the source, transformed-source, tool
commit and output identities across all receipts. It recursively rejects any
true publishing, paid, production-approval, readiness or full-review claim,
nonzero provider calls/cost, unsafe external writes, symlink ancestors,
unrecorded files and oversized media. It stages a new queue-owned review packet,
packages it with the existing shared private-review packager, reopens every
package/archive identity, then rechecks the external source before SQLite can
record success. A later delivery read rehashes both the staged packet and the
queue-owned package.

`PASS` establishes durable byte identity and offline lineage only. It does not
establish that the original source bytes were retained in this packet, that the
external tool itself ran in this queue, that the video was watched or heard,
that phone playback works, that the creative is competitive, or that it is
approved for production or publication. Those acceptance gates remain false.

Focused synthetic/adversarial tests:

```sh
python -m unittest -v integrations.content_control.test_external_media_job
```
