# REA evidence adapter — optional integration

Source: https://github.com/morluto/rea (MIT; review license and dependency versions before use).
Status: proposed integration, **not installed or executed in production**.

## Purpose
Augment the existing reverse-engineering department with evidence-backed investigations of software features. REA is an analysis tool, not an Instagram video extractor or a replacement for the Money Factory's research, economics, or QA gates.

## Execution requirements
- Node.js 22.19+, 24.11+, or 26+ and npm; check upstream for changes.
- For JavaScript/Electron static analysis: accessible, authorized local artifacts.
- For website analysis: Chrome-family browser and permitted access.
- For native binary analysis: separately provisioned supported analyzer.
- No paid provider, cloud service, or browser automation should be provisioned automatically.

## Adapter contract
Input:
```json
{"target_type":"javascript|website|android|native","target_reference":"approved path or URL","feature_question":"specific behavior to understand","authorization_evidence":"rights or permission basis","business_id":"existing Money Factory identifier"}
```
Output:
```json
{"tool":"REA","tool_version":"record installed version","status":"not_run|blocked|completed|failed","observations":[],"evidence":[],"limitations":[],"feature_spec":null,"test_plan":[],"provenance":{"target_reference":"","analysis_timestamp":""}}
```

## Gates
1. Require authorization and a bounded feature question. No access-control bypass, credential extraction, or unauthorized inspection.
2. Confirm runtime, pinned tool version, permitted target, and applicable license/terms.
3. Execute in a sandbox with minimal permissions; never run untrusted app code or install optional analyzers without approval.
4. Capture REA's evidence and unknowns. Mark uncertain conclusions as uncertain.
5. Convert findings into an original implementation specification and tests. Do not copy proprietary code or assets.
6. Pass results through existing Money Factory evidence, economics, readiness, security and release gates.
7. No publishing, spending, deployment, or external-account changes by this adapter.

## Validation checklist
- [ ] Confirm REA version and license at install time
- [ ] Verify Node runtime and dependency lock
- [ ] Inspect existing Money Factory reverse-engineering interfaces
- [ ] Wire adapter into actual execution path
- [ ] Test with an authorized open-source sample application
- [ ] Verify evidence provenance and failure behavior
- [ ] Confirm no regressions to existing tests
- [ ] Verify deployment and operational health

This document is an integration contract, not proof of a functioning installation.
