# Pinned q8 Kokoro auditions

Content Control already uses Python `kokoro==0.9.4` in `scripts/v2_free_voice.py`.
This alternative tests the official project's `kokoro-js==1.2.1` CPU ONNX path;
it does not replace the existing renderer, approved narration or speaker policy.
Each audition reads the entire approved script with one preset; it does not reproduce
per-character dialogue or assign a new production narrator. The only allowed stock presets are the existing assignments `am_adam`,
`am_fenrir`, and `am_michael`. There is no cloning, reference upload, provider API,
voice reassignment, service or publication operation.

Source: [hexgrad/kokoro at dfb907a](https://github.com/hexgrad/kokoro/tree/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro.js).
The canonical project links the [ONNX conversion](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX),
pinned here to `1939ad2a8e416c0acfeecc08a694d14ef25f2231`.
Code and model metadata declare Apache-2.0; retain dependency notices as well.
The model is exactly 92,361,116 bytes, SHA-256
`fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478`.
`model-manifest.json` also pins the configs and the three bundled stock voices.
The committed npm lock records exact resolved dependencies/integrities; installed
package bytes are not independently reauthenticated on each run.

## Isolated setup

Use Linux/WSL2, Python 3.11+, Node 24 and an operator-owned local disk directory.
Avoid memory-backed `/tmp` for dependencies/model storage. The tested npm tree
occupied about 409 MB plus the 92.4 MB model; actual installed sizes can vary.
These are explicit public downloads, not part of inference:

```bash
mkdir -p /path/to/kokoro-runtime
cp integrations/kokoro/package.json integrations/kokoro/package-lock.json /path/to/kokoro-runtime/
npm ci --prefix /path/to/kokoro-runtime --ignore-scripts --no-audit --no-fund
python -m integrations.kokoro.prepare_model --runtime /path/to/kokoro-runtime
```

No full-precision or alternative model weights are fetched. A mismatched existing
model is rejected, not overwritten. No global package, shell profile, host setting
or autostart is changed. Setup success is not an inference or quality result.

## One supervised audition

Use a reviewed, publication-disabled factual contract and its exact SHA-256:

```bash
python -m integrations.kokoro.preview \
  --runtime /path/to/kokoro-runtime \
  --contract /path/to/content-control/state/episode1-factual-contract.json \
  --contract-sha256 EXACT_REVIEWED_CONTRACT_SHA256 \
  --output-dir /new/path/to/audition \
  --voice am_adam
```

The wrapper holds the shared per-user admission lock through guardian cleanup,
but this explicit one-process experiment does not certify capacity admission or
24/7 operation. It binds execution to two inherited CPU affinity slots, a 180-second
wall deadline, per-process CPU-time hard limit 125 seconds, 64 MiB per-file limit,
256MiB JavaScript heap, and a 1.5 GiB process-tree RSS stop threshold sampled every
25 ms. **The RSS threshold is monitoring, not a kernel memory guarantee; CPU-time
limits are per process, not aggregate tree budgets.** Memory includes descendants
by PPid scans, including hosts without `/proc/PID/task/PID/children`. Unknown
memory observations fail closed. Native runtime memory is not covered by the
JavaScript heap cap; kernel-reported child peak RSS is also retained in output.

Inference strips inherited credentials/proxies/runtime hooks, disables remote
model loads and fetch, verifies pinned model/voice bytes, and retains sentence
text/token evidence. Empty, changed or truncated utterances cannot produce an
accepted receipt. Every output directory is new. Stop with Ctrl-C; the guardian
cleans owned processes and retains the shared lock until they exit.

`GENERATED_PENDING_REVIEW` proves only the bound offline generation. Compare
ASR word/numeric fidelity, original-versus-generated duration, and actual audio
for pronunciation, tone, pacing and character fit before considering any use.
Sentence segmentation and quantization can change pronunciation and prosody.
Upstream voice grades are training-data estimates, not independent quality proof.
An audition is not authorized to replace a production voice or change approved
caption/timing contracts. Failed/partial files remain diagnostic only.

Tests use real child processes for deadline/RSS cleanup and fixtures for model
mismatch, no-overwrite and text integrity; they do not claim model quality:

```bash
python -m unittest integrations.kokoro.test_preview -v
node --test integrations/kokoro/contract.test.mjs
```

## Observed offline auditions, 2026-11-21 UTC

See `validation-20261121.json` for exact hashes, raw ASR, resource receipts and limitations. Original speech was 26.184s; the same approved text produced 28.725s with `am_adam` and 32.5s with `am_michael`. Independent cached base.en ASR recovered all normalized words/amounts for all three. Normalization hides dollar/dollars differences in raw transcripts; these remain listening-review flags, not proven pronunciation defects. No naturalness or production approval is claimed. Both final outputs were generated through the committed bounded wrapper; original production audio and assigned voices remain unchanged.
