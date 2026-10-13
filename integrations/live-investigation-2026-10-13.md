# Live integration investigation — 2026-10-13

## Verified result

The historical HTTP 503 WORKER_NOT_CONFIGURED no longer reproduces on the live service. The endpoint now returns HTTP 200, backend github-actions, HOSTED_CPU_OPERATIONS_VERIFIED, production_ready false, persistent_worker_configured false, and publication_enabled false. No environment change was needed in this investigation.

The historical cause is the explicit missing-configuration branch in repository-integrations.js: without REPOSITORY_WORKER_BACKEND=github-actions or MONEY_FACTORY_ROOT, it returns WORKER_NOT_CONFIGURED. Its missing-worker regression test reproduces that branch. The existing hosted backend now reports verified CPU operations without claiming a resident worker or full production readiness.

Authorized Render workspace: tea-darsafojo6nc739844hg (cyzorcreations@gmail.com). Existing free service: srv-darsdb8u01pc73dn4i2g. Observed live deploy dep-db6ugfibt3mc73dsm8h0 uses content-control commit 2874a4402f3921198e69ba72b1df29541a8f78c9.

## Runtime evidence

- /health: HTTP 200; accepted V10 artifact hash and caption hash match.
- /media: downloaded bytes SHA-256 54f37c847c79e632e26648a3f31f11f24266d316217dd71025187b1924c1b127 matches live health; range request returns HTTP 206.
- /captions: HTTP 200.
- /api/integrations/status: HTTP 200; eight scoped CPU operations verified from run 38367673446. GitHub job records independently confirm installation and real execution through Content Control succeeded.
- /api/production/v2: HTTP 200 transport, BLOCKED production status; candidate_generated true, workflow_outcome failure, production_approved false.
- /v2/draft/media: HTTP 409; unfinished preview remains withheld.
- V2 run 38367398106: free voices, audio mixing, transcription, captions, Remotion render, and draft persistence succeeded. Inspect rendered candidate failed. Job logs report mean frame distance 0.36241420917585787 and p90 0.3696198413245506, with exit code 1.
- Independently inspected repository candidate public-review/v2-draft.mp4: SHA-256 807497c1c533195c8a563c22bfb9011c3599dd05b8d9f49b90719970acaa79af matches the live production report. ffprobe confirms 35.040998 seconds, 720x1280 H.264 video and AAC audio. This is technical evidence, not audiovisual/creative acceptance.

## Small correction

The watchdog previously derived machine_system_complete=true and COMPLETE solely from accepted V10 component checks. Its generator now preserves component GREEN while emitting COMPONENT_CHECKS_PASSED, machine_system_complete=false, production_ready=false, and explicit scope. The operations snapshot and system completion record use the same rule. Regression tests exercise both passing component checks and missing/failing states. Existing acceptance and publication gates remain intact.

Validation: 13 Node integration/production-status tests and two Python scope tests pass. The corrected full watchdog passes all existing component invariants. Missing-worker behavior is reproduced locally, not claimed as a current live failure.

No Render settings, service plan, paid infrastructure, rendering engine, character assets, voice selection, or acceptance thresholds were changed. Deployment manifest changes were unnecessary for the working live backend and were not included.

## Remaining limits

Full end-to-end production acceptance FAILS: the current candidate fails framewise style parity and lacks completed creative acceptance. The Render process serves/validates persisted media; it is not a resident GPU generation worker. Hosted CPU checks cover eight named operations, not every upstream product feature. Provider-backed generation and persistent hosted project state remain unverified. Wan needs a CUDA-capable host and model weights absent from this free Node deployment and standard CPU runner. No paid host was provisioned. Publication remains disabled.

Evidence: Money-factory/integrations/live-content-control-2026-10-13.json, reproducible with python integrations/check_live_content_control.py.
