# Local isolated-speech diagnostics

This adapter adds **DNSMOS P.835** speech (`SIG`), background (`BAK`) and overall
(`OVRL`) diagnostics to the existing FFmpeg level/decode checks and Whisper
transcription checks. It does not replace those checks or listening review.
It does not score an intentional music mix, certify TTS naturalness, or approve
creative quality, synchronization or publishing. `DIAGNOSTIC_COMPLETE` means
inference completed; there is deliberately no quality approval threshold.

Only operator-identified **isolated narration**, 16 kHz mono PCM16 WAV, 9.01–120
seconds is accepted. The assertion flag is not an automatic speech detector.
Short clips are rejected instead of repeated. Silent inputs are rejected.
Scores use 9.01-second windows with a one-second step; the report identifies
the unscored tail. Inspect the windows, not just the average.

## Local setup and use

Use an isolated Python 3.11+ environment; the tested versions are pinned in
`requirements.txt`. Installation and the explicit model download require
network access; scoring itself contains no network or provider client.
Do not put models or generated media into Git.

```bash
python3 -m venv runtime/dnsmos-env
runtime/dnsmos-env/bin/python -m pip install -r integrations/dnsmos/requirements.txt
mkdir -p runtime/dnsmos-models
curl --fail --location --max-time 60 \
  https://raw.githubusercontent.com/microsoft/DNS-Challenge/785ab12275d5cf9341c5e946b0eee9f8825ece3b/DNSMOS/DNSMOS/sig_bak_ovr.onnx \
  --output runtime/dnsmos-models/sig_bak_ovr.onnx
runtime/dnsmos-env/bin/python -m integrations.dnsmos.score \
  --audio /absolute/path/isolated-narration-16k-mono.wav \
  --model runtime/dnsmos-models/sig_bak_ovr.onnx --isolated-speech
```

The adapter verifies the exact 1,157,965-byte model against the SHA-256 in
`model.json` before loading its bytes. A missing or changed model is blocked;
it is never downloaded automatically. The ONNX CPU provider runs sequentially
with one intra-operation and one inter-operation thread. One diagnostic job at
a time is the initial operating policy; this CLI is not a persistent worker or
an admission-budget override. The duration limit bounds workload, not a hard
wall-clock deadline. Use the existing owned-process/admission wrapper when
adding it to a production queue. No host deployment is included here.

For the existing Episode1 producer, convert its isolated narration source:

```bash
CONTENT_CONTROL_ROOT=/absolute/path/content-control
ffmpeg -hide_banner -loglevel error -n \
  -i "$CONTENT_CONTROL_ROOT/public/audio/episode1-narration.mp3" \
  -ar 16000 -ac 1 -c:a pcm_s16le runtime/episode1-narration-16k.wav
runtime/dnsmos-env/bin/python -m integrations.dnsmos.score \
  --audio runtime/episode1-narration-16k.wav \
  --model runtime/dnsmos-models/sig_bak_ovr.onnx --isolated-speech
```

For the current V2 picture-video packet, use its **`artifact/voice.wav`**, not
`mix.wav` or the MP4 audio. Set `CYZOR_V2_PACKET` to that packet's local root,
then substitute `"$CYZOR_V2_PACKET/artifact/voice.wav"` for the input above.
The validated V2 voice SHA-256 is
`e324ef9ed317b801ebab275d6cef5334dc77482da4bc4003d5641e5dde535be3`.
Verify the identity before comparing against the recorded proof.

```bash
CYZOR_DNSMOS_TEST_MODEL=runtime/dnsmos-models/sig_bak_ovr.onnx \
  runtime/dnsmos-env/bin/python -m unittest integrations.dnsmos.test_score
```

The actual inference regression uses a synthetic tone only to test execution,
identity and reporting; it is not evidence of speech quality. A separate
`runtime-proof.json` records an owned narration sample and deterministic noisy
copy. These are diagnostics, not a universal calibration or an approval rule.
Run `python -m integrations.dnsmos.validate_fixture --help` for the exact
reproducible local fixture recipe. It writes a new output directory and never
changes the input. No supplied media is uploaded.

```bash
runtime/dnsmos-env/bin/python -m integrations.dnsmos.validate_fixture \
  --audio runtime/episode1-narration-16k.wav \
  --model runtime/dnsmos-models/sig_bak_ovr.onnx \
  --output-dir runtime/dnsmos-fixture
```

Real-time speed and peak memory must be measured on the intended host; no GPU
is required by this CPU route. Model size is not total process RAM.

## Attribution and adaptation

Source: Microsoft [DNS-Challenge/DNSMOS](https://github.com/microsoft/DNS-Challenge/tree/785ab12275d5cf9341c5e946b0eee9f8825ece3b/DNSMOS),
revision `785ab12275d5cf9341c5e946b0eee9f8825ece3b`.
The repository/model license is [CC BY 4.0](https://github.com/microsoft/DNS-Challenge/blob/785ab12275d5cf9341c5e946b0eee9f8825ece3b/LICENSE).
The license text is retained in `LICENSE-UPSTREAM.txt`. Changes: bounded single
file input, explicit isolated-speech scope, local model identity verification,
CPU thread limits, stdlib WAV loading, no resampling, no short-clip repetition,
no P.808 model, no default thread pool, and non-approval JSON receipts. The
P.835 model input and regular calibration coefficients follow upstream.

Cite Chandan K. A. Reddy, Vishak Gopal and Ross Cutler, *DNSMOS P.835: A
Non-Intrusive Perceptual Objective Speech Quality Metric to Evaluate Noise
Suppressors*, ICASSP 2022 ([paper](https://arxiv.org/abs/2110.01763)).
The upstream intended domain is noise-suppression evaluation; extrapolating
these scores to expressive synthesis, musical backgrounds or artistic appeal
requires separate human validation.
