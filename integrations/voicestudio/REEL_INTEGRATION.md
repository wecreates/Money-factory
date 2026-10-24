# VoiceStudio → Content Control review boundary

## What changed

`reel_adapter.py` connects a selected Content Control CCSD dialogue line to the
existing Money Factory `voicestudio/synthesize` request contract. It also validates
a returned WAV against that exact script segment and the existing generation
metadata. The common private worker dispatches these additive operations. No
production voice selection, synthesis runner, source pin or current media changes.

The existing runtime remains `4df5033e5a1a92e22936fb4d7d2d39e03cf10a91`, with
KittenTTS model revision `c02725660cea441db4c383af69f1f26f5cd00947`. The newly
downloaded VoiceStudio source at `311effa5f7b9ca8f2559de7f91fccf35d686e981` was
statically reviewed only. Its presence does not upgrade or validate the runtime.

## Operations

All jobs require `tool: voicestudio`, `operation`, `publication_enabled: false`
and `paid_generation_enabled: false`. Non-status jobs use `input`, a local JSON
file. The worker owns writing the returned JSON to the requested new output path.

- `status`: reports the preserved runtime pin, reviewed download pin and blockers.
  `status: PASS` means the status query completed, not that inference is available.
- `prepare-narration`: input contains `ccsd` (an inline CCSD object with
  publication disabled), `scene_id`, explicit zero-based `dialogue_index`, explicit
  Kitten `voice`, optional `speed`, and both disabled flags. Returns `request`,
  which can be saved unchanged as input to the existing `synthesize` job. It
  preserves original text bytes and includes scene/text/CCSD hashes and timing.
  Speaker roles are not reassigned; the nonverbal cashback_goblin is rejected.
- `validate-export`: input contains `preparation` (the original prepare input),
  `audio` (local WAV path), `generation` (existing `.generation.json` path) and
  both disabled flags. It checks source/model/model-file/text/voice/speed hashes,
  full PCM frame availability, rate/channels, RMS/clipping, and scene duration.
  Returns a technical candidate requiring transcript, speaker/listening, creative
  and rights reviews. It never writes approved media or active voice manifests.

Example preparation input:

```json
{
  "ccsd": {
    "publication_enabled": false,
    "scenes": [{"id":"hook","start":0,"end":3,"audio":{"dialogue":[
      {"speaker":"narrator","text":"A small example for review."}
    ]}}]
  },
  "scene_id":"hook",
  "dialogue_index":0,
  "voice":"expr-voice-2-f",
  "speed":1.0,
  "publication_enabled":false,
  "paid_generation_enabled":false
}
```

The generated request is compatible with the existing validator; it does not
schedule speech or establish English-language or pronunciation accuracy.
The validator's local path is a locator, not a retained immutable copy. Rehash
before downstream use. Supplied generation metadata is consistency-checked, not
cryptographically authenticated, and an alleged watermark is not independently
detected. Files must be private and quiescent during intake; these paths are not
safe to expose as a public arbitrary-file endpoint.

## Static source review and deployment limits

The downloaded source exposes `/v1/audio/speech`, but that endpoint may load or
download an engine on demand and supports profile-based voice cloning. This
integration deliberately uses the existing narrow preset runner rather than
adding an unconstrained API connection.

The application is AGPL-3.0-only. Its default OmniVoice weights are identified as
CC-BY-NC; tokenizer and other model components have separate terms. The existing
Kitten preset model was selected separately, but neither its metadata nor the
application's license establishes completed commercial/output clearance. No
cloning consent or commercial permission is inferred.

The repository includes `bin/omnivoice-tts-windows-x86_64.exe`, remote installer
scripts, lifecycle hooks that install dependencies, and a large ML dependency
graph including direct-wheel sources. None was executed, installed or accepted
as trusted through this task. New runtime/source upgrades require separate
execution approval and a real smoke test. Existing historical synthesis receipts
are retained as historical, not fresh health evidence.

Sources:
- https://github.com/wecreates/Money-factory/blob/bb35b393f7e36e5ad73fbec3905efacd4c4234a6/integrations/voicestudio/runner.py
- https://github.com/wecreates/Money-factory/blob/bb35b393f7e36e5ad73fbec3905efacd4c4234a6/integrations/voicestudio/hosted-verification.json
- https://github.com/debpalash/VoiceStudio/blob/311effa5f7b9ca8f2559de7f91fccf35d686e981/LICENSE-NOTICE.md
- https://github.com/debpalash/VoiceStudio/blob/311effa5f7b9ca8f2559de7f91fccf35d686e981/backend/api/routers/openai_compat.py

Tests: from `integrations`, run `python -m unittest -v test_reel_voice_video`.
The PCM fixtures are generated sine waves, not evidence of real speech generation.
