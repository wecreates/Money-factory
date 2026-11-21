# Exact-cycle REA Video diagnostics

`analyze_cycle(cycle_dir, output, runtime=..., timeout=300)` connects the installed
[JuneYaooo/rea-video](https://github.com/JuneYaooo/rea-video) analyzer to a completed
CYZOR cycle. It validates the cycle's original render, packaged files, ZIP,
editorial input, captions, and receipts before execution and again afterward.
It does not alter that cycle or record a reviewer approval.

The host must already have the Python environment installed from commit
`86486c6e104b917fb4b6a2d6501134686c05b219`, with OCR dependencies and the verified
YuNet model cached. There is no install/download step in this adapter.

```bash
export REA_VIDEO_MODELS=/absolute/path/to/rea-video-models
python -m integrations.content_control.cycle_review \
  --analyze \
  --cycle-dir /absolute/path/to/completed-cycle \
  --output /absolute/path/to/new-diagnostics \
  --rea-runtime /absolute/path/to/rea-video/.venv/bin/python \
  --timeout 300
```

`--rea-runtime` names the installed **Python interpreter**, not the `rea-video`
console script. Standard virtualenv interpreter symlinks are supported; cycle,
output, source, model, and diagnostic artifact symlinks are rejected. The output
must be a fresh directory outside the cycle. Without `REA_VIDEO_MODELS`, the
model is expected under `~/.cache/rea-video/models`.

The run uses a copied candidate and an isolated preferences/model directory.
Provider environment variables and `.env` loading are excluded. Python socket
connections and upstream fetch calls are denied; this is an application guard
for pinned trusted code, not a general OS network sandbox. VLM, ASR, speaker
separation, stem extraction, moments, survey, and packaging analysis are disabled.
Shot-level OCR remains enabled and must initialize successfully. OpenCV and
common math libraries are bounded to two threads; the CLI uses one worker.
The existing process guardian owns subprocess cleanup on timeout and parent
exit. Logs retain only their last 64 KiB.

Successful execution returns `DIAGNOSTIC_COMPLETE` in `analysis.json`, binding:

- The exact candidate and all verified cycle input identities.
- The pinned analyzer commit, tracked package-file hashes, and dependency versions.
- The adapter source hash and verified YuNet model hash.
- The diagnostic artifact manifest, including `diagnostics/VIDEO.md`,
  `diagnostics/storyboard.jpg`, and `diagnostics/breakdown.json`.

Read `diagnostics/VIDEO.md` first, then inspect the storyboard and individual
shot images. Machine-detected boundaries can merge multiple editorial cuts.
OCR and pixel/audio statistics cannot establish natural voice quality, factual
accuracy, creative quality, or complete audiovisual comparison. Publication,
production approval, and full audiovisual approval remain false. Reports retain
these limitations even after a successful analyzer execution.

Failures after output creation preserve a `BLOCKED` receipt and bounded logs.
A missing cached model, changed cycle, source pin mismatch, modified analyzer,
missing OCR, symlink, unexpected external-model operation, or changed candidate
cannot produce a completion receipt. Invalid prerequisites fail before launch.

Validation:

```bash
python -m unittest integrations.rea_video.test_analyze_cycle -v
```

Unit fixtures are deliberately synthetic and do not prove real analysis. The
separate actual-run receipt must demonstrate execution against a real completed
cycle before claiming the integration works on that host.

An [actual cycle execution receipt](cycle-analysis-proof-20261121.json) records
the November 21, 2026 cloud-workspace run (18:52:31–18:52:54 UTC) against the
unpublished six-scene candidate. The analyzer detected only one segment, so
this proves the connection executes, not complete scene detection or creative
approval. Actual PC/VPN-host integration remains unverified.
