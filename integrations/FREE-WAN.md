# Free Wan integration — implementation and live test

## Scope and status

A separate wan21/generate-free operation calls a pinned Hugging Face ZeroGPU image-to-video provider through Money Factory's existing integrations/run.py. Content Control uses its existing scripts/repository_tools.py bridge, unchanged. The existing local Wan text-to-video operation remains intact. This is an optional quota-limited asset generator, not a replacement for Remotion or a production-readiness approval.

Implemented: pinned provider revision and API schema, anonymous requests with no token/billing credentials, no retries or paid fallback, bounded input/duration/downloads, explicit per-job external-processing approval, ffprobe/full-decode validation, SHA-256 receipts, and hosted reviewed-job/persistence support. Hosted workflow skips local CUDA/model installation for generate-free. Media remains in the existing retention-bound workflow artifact; it is not automatically added to an accepted timeline or published.

## Observed live test, 2026-10-13

Provider metadata reported RUNNING on ZeroGPU, revision d8ad2caa4a290086c86e4df59e13789a88ce0e5d; live API schema matched. A generic newly drawn stick figure with no production assets or private data was submitted via Content Control's existing bridge. Upload and submission completed, but the event stream returned event:error with data:null. No video or passing receipt was produced. Authentication, quota, and provider runtime failure cannot be distinguished from that response. Status stays LIVE_GENERATION_NOT_VERIFIED / production_ready=false.

An earlier attempt to submit a production-derived frame was blocked by automatic approval review; it was replaced with the generic fixture. Production-content sharing remains unapproved.

Hugging Face account londneckdart is authenticated and non-Pro. The connector exposes read-repos/read-mcp/jobs scopes, but no repository write scope, so it cannot create an owned ZeroGPU Space. No paid HF Jobs were launched. Cloud-browser setup of an owned free Space is the next candidate, subject to account eligibility and live validation.

The existing CPU verification run 38371847700 completed successfully including execution and recording. The free CPU animation path is already operational at the render stage; its current video's style-parity/creative acceptance remains unresolved. This GPU adapter does not waive those gates.

## Job contract

Use tool wan21, operation generate-free, a PNG input under 5 MiB, a new output path, prompt (1–1200 chars), duration_seconds (0.3–2), seed (integer), publication_enabled=false, paid_generation_enabled=false, and external_processing_approved=true only after approval to share that particular image/prompt. Run through the existing Content Control repository_tools.py bridge. For GitHub-hosted jobs, use a reviewed file and image under integrations/jobs; the existing repository-job.yml sets output paths. There is no public unauthenticated execution endpoint.

## Free service limits

Official documentation: https://huggingface.co/docs/hub/spaces-zerogpu
Free personal accounts with verified email and age over 30 days can host up to two ZeroGPU Spaces. Included usage is quota-limited (documentation lists five GPU minutes/day for free accounts, two for anonymous). Availability is not guaranteed. Do not rotate identities or retry around quotas. Hosted input files in these public repositories must be approved for public disclosure.

Regression validation: free-Wan parameter/output-contract tests, existing hosted-job tests, and persistence tests pass. Successful live GPU generation has NOT been established.
