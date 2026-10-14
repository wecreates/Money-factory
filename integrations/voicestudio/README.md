# VoiceStudio CPU narration

This focused integration calls the real `KittenTTSBackend` from VoiceStudio revision `4df5033e5a1a92e22936fb4d7d2d39e03cf10a91`, preserves its engine-licence check, and routes output through its `mark_synthetic` function. It does not install the entire desktop application or replace Content Control's existing voices.

`setup_runtime.setup(upstream, runtime)` installs CPU PyTorch 2.8.0, the official KittenTTS 0.8.1 wheel, pinned direct dependencies, the spaCy English pipeline, and the approximately 80 MB Kitten model. Model revision is `c02725660cea441db4c383af69f1f26f5cd00947`; setup records hashes of config, ONNX and voice files. The SDK has no revision argument, so its dedicated cache's offline `main` reference points to this exact snapshot. Inference rechecks revision and hashes and sets `HF_HUB_OFFLINE=1`.

Example input:

```json
{
  "text": "Welcome to CYZOR. This is synthetic narration generated locally.",
  "voice": "expr-voice-2-f",
  "speed": 1.0,
  "language": "en",
  "publication_enabled": false,
  "paid_generation_enabled": false
}
```

```sh
/absolute/runtime/voicestudio/bin/python integrations/voicestudio/runner.py \
  --upstream /absolute/VoiceStudio --runtime /absolute/runtime/voicestudio \
  --input /absolute/request.json --output /new/narration.wav
```

Supported voices are `expr-voice-2-m/f` through `expr-voice-5-m/f`. Text is bounded to 1,200 characters, English only; speed 0.75–1.5. Output is mono 24 kHz PCM16 WAV plus `.generation.json`, containing the exact source/model/text/output hashes, duration and signal validation, synthetic provenance, and actual watermark outcome. Existing outputs are rejected.

AudioSeal is optional upstream and is not installed in this focused runtime. The upstream provenance function is called, but may return audio unchanged; metadata explicitly records `watermark_applied: false` in that case. Synthetic provenance metadata is not proof of an embedded watermark. No quality-listening approval is inferred from signal validation.

VoiceStudio application code is AGPL-3.0-only. Kitten's SDK is MIT; the selected model's upstream metadata declares Apache-2.0. VoiceStudio's registry still marks full component/output rights review incomplete. No licence acceptance is fabricated, no commercial rights are certified, and publication stays disabled. There is no voice cloning, emotion control, GPU requirement, paid provider, or cloud inference. First setup downloads free dependencies and model files; generation is offline. The install includes CPU PyTorch for VoiceStudio's tensor interface even though Kitten inference itself uses ONNX.

## Verified hosted execution

[Run 38624721568](https://github.com/wecreates/Money-factory/actions/runs/38624721568) generated a real 14.275-second, 24 kHz mono narration and passed normal result recording. The artifact digest, exact model/source hashes and waveform checks are in `hosted-verification.json`. The WAV is retained for 30 days; generation metadata and the receipt are durable in `integrations/results/runs/38624721568-1`. The stronger provenance validator also accepted this downloaded, hash-verified artifact.
