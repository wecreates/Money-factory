# Queued offline external-media review admission

`content-control-external-media` admits one already-produced, free/offline
OpenMontage safe-reframe packet to the durable queue. It does **not** run
OpenMontage, FFmpeg, Remotion, a model, a provider, a browser, or any network
request. The operator supplies the artifact root on the worker command line;
queued data cannot select a path, command, URL, provider, or runtime.
Use an operator-owned input root with stable, trusted ancestor directories.
The symlink checks and byte pins protect ordinary queue intake. They do not
make the input path a filesystem sandbox against concurrent hostile changes
to its ancestor directories.

The immutable request pins all relevant lineage boundaries:

```json
{
  "id": "openmontage-safe-reframe-001",
  "adapter": "content-control-external-media",
  "request": {
    "operation": "package-openmontage-safe-reframe-with-source-bytes",
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
- `source-evidence/original.mp4` and `source-evidence/trimmed.mp4`, with no
  other files in that directory. Together they must fit within 256 MiB.
  Their hashes must match the exact immutable source and transformed-source
  pins, and the prior receipt must record a successful zero-cost trimmer result
  with that transformed-source hash.

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
record success. The source-byte operation also copies both inputs and both
producer receipts into the private queue attempt and rehashes the staged
copies before completion. A later delivery read repeats these checks against
the queue-owned evidence and package, independent of the operator input
directory. Source inputs and producer receipts stay in queue storage and are
excluded from review exports.

Delivery reports distinguish `queue_owned_source_bytes_rehashed` from
`receipt_attested_only`. The earlier `package-openmontage-safe-reframe`
operation retains its prior request and durable package format and returns
`receipt_attested_only` because the original and trimmed bytes were never
retained by that operation. Use the source-byte operation for new byte-evidence
jobs. Both modes preserve unpublished review status. Playback, phone testing,
creative acceptance, production approval and external tool execution remain
separate and unverified by this adapter.

Focused synthetic/adversarial tests:

```sh
python -m unittest -v integrations.content_control.test_external_media_job
```
