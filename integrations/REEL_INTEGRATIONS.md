# Source-pinned offline integrations, 2026-10-23

The existing `integrations/run.py` now dispatches explicit project-owned offline bridge operations for OpenSEO, WeKnora, OpenWhispr, OpenProject, OpenHiggsfield, VoiceStudio, and Hypit. Configuration lives in `repositories.json` → `external_bridges`; the actual callable allowlist and expected source pins live in `reel_bridges.py`.

This is working import/export/preparation code connected to the existing worker. It is not installation or live operation of seven upstream applications. Source archives were reviewed without executing their install scripts, binaries, model downloads, or provider clients. Each adapter has its own README and tests.

## How to run

Use the existing worker command: `python integrations/run.py JOB.json --runtime /tmp/cyzor-offline`.

Jobs identify `tool`, `operation`, a new `output` path, and literal JSON `false` for both `publication_enabled` and `paid_generation_enabled`. Transformation jobs include an `input` path; readiness/status jobs need no input. `network_enabled` and `paid_services_enabled` cannot be enabled. The worker writes the returned JSON and an adjacent `.receipt.json` with SHA-256, exact source pin and an explicit `project_owned_offline_adapter` execution kind. BLOCKED bridge results produce BLOCKED receipts and CLI exit code 2; invalid input exits 1. Outputs are never overwritten.

## Existing integrations retained

- The seven original worker repositories and their verification rules are unchanged.
- Existing VoiceStudio `synthesize` continues to use revision `4df5033e5a1a92e22936fb4d7d2d39e03cf10a91`. The newly reviewed VoiceStudio archive at `311effa5f7b9ca8f2559de7f91fccf35d686e981` supplies the separate export/preparation contract. Its newer source was not installed.
- Content Control's existing `/api/integrations/status` exposes `external_bridges` separately from verified hosted operations. Registration never increments hosted-operation counts or implies production readiness. No public execution endpoint is added.
- Current production media and render/caption paths are untouched.

## Remaining acceptance

Offline bridge tests and real fixture jobs establish only the named transformations. Production/runtime readiness remains false. Real provider generation, microphone transcription, service installation, private knowledge transfer, authentication, live work-package creation, payment, publication, deployment and merging are not performed by this candidate.

OpenHiggsfield has no discovered upstream license, so no upstream source was copied into product code. Hypit's source-available license restricts third-party commercial service and commercial redistribution; internal use does not grant those rights. AGPL/GPL applications remain separate, with no copying into these adapters. Preserve and review upstream notices before any future installation or distribution.
