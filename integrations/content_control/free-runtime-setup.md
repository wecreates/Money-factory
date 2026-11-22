# Restore the free production runtimes

Use Python 3.12 and isolated environments. `requirements-voice.lock.txt` in
Content Control is a legacy Cartesia dependency list, not this free workflow.
These are tested direct compatibility pins, not a complete transitive lock.
Setup downloads public packages/models; production then runs offline with no
paid provider calls. No machine services or publishing settings are changed.

Set `CC_ROOT` to a clean trusted Content Control checkout containing the pinned
`scripts/v2_free_voice.py`; set `RUN_ROOT` to a new workspace directory. Run from
the Money Factory repository. `uv` was used for the verified restoration:

```sh
uv venv --python 3.12 "$RUN_ROOT/kokoro-runtime"
uv pip install --python "$RUN_ROOT/kokoro-runtime/bin/python" \
  torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python "$RUN_ROOT/kokoro-runtime/bin/python" \
  -r integrations/content_control/requirements-free-voice.txt
uv pip install --python "$RUN_ROOT/kokoro-runtime/bin/python" \
  https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
uv venv --python 3.12 "$RUN_ROOT/asr-runtime"
uv pip install --python "$RUN_ROOT/asr-runtime/bin/python" \
  faster-whisper==1.2.1 socksio==1.0.0
```

The CPU wheel must report `torch.version.cuda is None`. Keep Dave `am_fenrir`,
Points Monk `am_michael`, narrator `am_adam`. The English language package must
be installed before offline synthesis. `socksio` supports an existing SOCKS
transport; do not remove configured network controls to make setup succeed.

Download and verify assets separately from production. With the voice environment,
set `HF_HOME=$RUN_ROOT/kokoro-models`, load the trusted checkout's
`scripts/v2_free_voice.py`, and call `pinned_assets()`. This downloads and verifies
five files at revision `f3ff3571791e39611d31c381e3a41a3af07b4987`.

With the ASR environment and `HF_HOME=$RUN_ROOT/asr-models`, call
`huggingface_hub.hf_hub_download` for repository `Systran/faster-whisper-base.en`,
revision `3d3d5dee26484f91867d81cb899cfcf72b96be6c`, separately for `config.json`,
`model.bin`, `tokenizer.json`, and `vocabulary.txt`. Do not download extra snapshot
files: the production verifier allows exactly these four assets, checks sizes
and hashes before loading, ignores mutable `refs/main`, and records identity in
the ASR receipt. Normal Hugging Face links to blobs inside the cache work.

Run the existing cycle with `HF_HOME=$RUN_ROOT/kokoro-models`,
`CYZOR_ASR_HF_HOME=$RUN_ROOT/asr-models`, both new Python paths and the trusted
Content Control checkout. Avoid an inherited `HF_HUB_CACHE` pointing to another
cache; when set it takes precedence over `HF_HOME`. Use `--checkpoint` and retain
its ZIP and external hash durably. See [the cycle runbook](content-cycle.md).
Runtime success establishes execution, not natural voice quality, full audiovisual
acceptance, PC/VPN-host availability, or a persistent worker.

The [actual restoration receipt](runtime-restoration-proof-20261121.json) records
a fresh six-scene cycle completed at 22:47:10 UTC on November 21, 2026, plus
the saved checkpoint identity. Container duration is 34.585 seconds; the ASR
helper reports decoded/padded analysis duration separately. Neither duration
is a listening-quality attestation.

On November 22 the documented isolated setup was repeated after local runtimes
were lost. All nine pinned assets were independently hash-checked; the latest
durable checkpoint was recovered and its unchanged brief/lineage re-executed.
The fresh cycle and an explicit caption-rebased excerpt completed technically,
and a new checkpoint restored with equal inspection identities. See the
[dated recovery evidence](runtime-recovery-proof-20261122.json). This is local
standalone recovery, not intended-host admission, autonomous topic discovery,
listening approval or 24-hour operation.
