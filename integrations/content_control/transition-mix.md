# Offline transition mix

`cycle_transition_mix.py` adds a small original transition cue to the measured
post-narration tail between rendered scenes. It consumes an already completed
`render/` directory and creates a separate candidate; it never changes the
source render.

```bash
PUBLICATION_ENABLED=false PAID_GENERATION_ENABLED=false \
python -m integrations.content_control.cycle_transition_mix \
  --render-root /absolute/path/to/cycle/render \
  --output /absolute/new/path/to/transition-mix
```

The command requires two or more scenes and at least 240 ms between measured
narration end and the scene boundary. Each 160 ms cue ends 40 ms before the
boundary, so the command fails closed instead of placing sound over narration.
The cue and full-length stem are generated locally as mono 24 kHz PCM. No
downloaded, licensed, model-generated, or paid asset is used.

`mix.json` binds the source candidate, renderer receipt, timeline, voice
receipt, each exact assigned voice WAV, cue, stem, placements, unchanged encoded
picture stream, and decoded signal measurements. Cue-window energy is a
technical presence check only. A passing receipt remains
`AWAITING_LISTENING_REVIEW` with publishing, paid generation, production
approval, production readiness, full audiovisual review, and listening
verification all false. A person must still listen to the complete mix for
voice naturalness, pronunciation, cue taste, balance, timing, and creative
acceptance.
