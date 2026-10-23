"""Content Control dialogue → existing reviewed VoiceStudio narration contract.

No imports or execution of downloaded VoiceStudio code, no model installation,
and no changes to active Content Control voices. Synthesis remains the existing
separately reviewed `voicestudio/synthesize` operation.
"""
from array import array
import io
import math
from pathlib import Path
import sys
import wave

from reel_media import digest, json_digest, read_bytes, read_json, require_disabled, result

RUNTIME_REVISION = '4df5033e5a1a92e22936fb4d7d2d39e03cf10a91'
REVIEWED_DOWNLOAD_REVISION = '311effa5f7b9ca8f2559de7f91fccf35d686e981'
MODEL = 'KittenML/kitten-tts-mini-0.8'
MODEL_REVISION = 'c02725660cea441db4c383af69f1f26f5cd00947'
MODEL_FILES = {
    'config.json': '6b160bc9b19e24ecb21e84bc14f8a7da21fdf47ec72d42450bc5cf514b61804a',
    'kitten_tts_mini_v0_8.onnx': '0f5bbae4fc4800c98dbc544a87ecfa79510de2fb8222db30d12e5bfe9177df91',
    'voices.npz': '40ad2638952b77b7b2f30127e2608e169fc69dd256b53bd8aaa3409a33193c42',
}
VOICES = frozenset(f'expr-voice-{n}-{sex}' for n in range(2, 6) for sex in ('m', 'f'))


def prepare_narration(data):
    require_disabled(data)
    if set(data) - {'ccsd', 'scene_id', 'dialogue_index', 'voice', 'speed',
                    'publication_enabled', 'paid_generation_enabled'}:
        raise ValueError('Unsupported narration preparation option')
    ccsd = data.get('ccsd')
    if not isinstance(ccsd, dict) or ccsd.get('publication_enabled') is not False:
        raise ValueError('Publication-disabled CCSD required')
    scene_id = data.get('scene_id')
    if not isinstance(scene_id, str) or not scene_id:
        raise ValueError('Explicit scene ID required')
    scenes = ccsd.get('scenes')
    if not isinstance(scenes, list) or len(scenes) > 1000 or any(not isinstance(s, dict) for s in scenes):
        raise ValueError('Bounded CCSD scenes required')
    matches = [scene for scene in scenes if scene.get('id') == scene_id]
    if len(matches) != 1:
        raise ValueError('Scene ID must identify exactly one scene')
    scene = matches[0]
    start, end = scene.get('start'), scene.get('end')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
        raise ValueError('Finite scene start/end required')
    audio = scene.get('audio')
    dialogue = audio.get('dialogue') if isinstance(audio, dict) else None
    index = data.get('dialogue_index')
    if not isinstance(dialogue, list) or type(index) is not int or not 0 <= index < len(dialogue):
        raise ValueError('Explicit valid dialogue_index required')
    line = dialogue[index]
    if not isinstance(line, dict):
        raise ValueError('Dialogue object required')
    text, speaker = line.get('text'), line.get('speaker')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200 or not any(c.isalpha() for c in text):
        raise ValueError('Provide 1..1200 characters of speakable text')
    if not isinstance(speaker, str) or not speaker.strip() or speaker == 'cashback_goblin':
        raise ValueError('Explicit verbal speaker required; nonverbal roles stay silent')
    voice, speed = data.get('voice'), data.get('speed', 1.0)
    if not isinstance(voice, str) or voice not in VOICES:
        raise ValueError('Explicit reviewed Kitten preset required')
    if type(speed) not in (int, float) or not math.isfinite(speed) or not .75 <= speed <= 1.5:
        raise ValueError('Speed must be between .75 and 1.5')
    request = {'text': text, 'voice': voice, 'speed': float(speed), 'language': 'en',
               'publication_enabled': False, 'paid_generation_enabled': False}
    return result('voicestudio', 'prepare-narration',
        runtime_revision=RUNTIME_REVISION, reviewed_download_revision=REVIEWED_DOWNLOAD_REVISION,
        runtime_status='EXISTING_PIN_PRESERVED_NOT_PROBED', request=request,
        request_sha256=json_digest(request), ccsd_sha256=json_digest(ccsd),
        segment={'scene_id': scene_id, 'dialogue_index': index, 'speaker': speaker,
                 'start_seconds': start, 'end_seconds': end,
                 'window_seconds': end - start, 'text_sha256': digest(text.encode())},
        next_operation='voicestudio/synthesize', voice_assignment_changed=False,
        scope='Prepared one optional English preset narration input; no speech generated or voice approved')


def validate_export(data):
    require_disabled(data)
    if set(data) - {'preparation', 'audio', 'generation', 'publication_enabled', 'paid_generation_enabled'}:
        raise ValueError('Unsupported export validation option')
    prepared = prepare_narration(data.get('preparation'))
    request = prepared['request']
    raw = read_bytes(data.get('audio'), 10 * 1024 * 1024)
    generation = read_json(data.get('generation'))
    require_disabled(generation)
    expected = {'status': 'PASS', 'tool': 'voicestudio', 'operation': 'synthesize',
        'engine': 'kittentts', 'upstream_revision': RUNTIME_REVISION,
        'model': MODEL, 'model_revision': MODEL_REVISION,
        'model_files_sha256': MODEL_FILES,
        'text_sha256': digest(request['text'].encode()), 'voice': request['voice'],
        'speed': request['speed'], 'language': 'en', 'output_sha256': digest(raw)}
    if any(generation.get(key) != value for key, value in expected.items()):
        raise ValueError('Generation provenance does not match the prepared narration and audio')
    if generation.get('synthetic') is not True:
        raise ValueError('Synthetic provenance required')
    if type(generation.get('speed')) not in (int, float):
        raise ValueError('Numeric generation speed required')
    with wave.open(io.BytesIO(raw), 'rb') as audio:
        channels, width, rate, count = (audio.getnchannels(), audio.getsampwidth(),
                                       audio.getframerate(), audio.getnframes())
        if channels != 1 or width != 2 or rate != 24000 or not .25 <= count / rate <= 180:
            raise ValueError('Expected bounded 24 kHz mono PCM16 speech')
        pcm = audio.readframes(count)
    if len(pcm) != count * 2:
        raise ValueError('Truncated speech output')
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    rms = math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / count)
    clipped = sum(abs(sample) >= 32760 for sample in samples) / count
    if rms < .00001 or clipped > .01:
        raise ValueError('Silent or excessively clipped speech output')
    duration = count / rate
    if duration > prepared['segment']['window_seconds']:
        raise ValueError('Narration exceeds the CCSD dialogue window; retake required')
    return result('voicestudio', 'validate-export', candidate={
        'kind': 'audio', 'state': 'TECHNICAL_CANDIDATE_REQUIRES_REVIEW',
        'local_path': str(Path(data['audio']).absolute()), 'revalidate_before_use': True,
        'sha256': digest(raw), 'request_sha256': prepared['request_sha256'],
        'segment': prepared['segment'], 'duration_seconds': duration,
        'sample_rate': rate, 'channels': channels, 'rms': rms,
        'clipped_fraction': clipped, 'synthetic': True,
        'watermark_applied': generation.get('watermark_applied') is True,
        'watermark_independently_verified': False,
        'generation_metadata_sha256': json_digest(generation)},
        voice_assignment_changed=False,
        required_reviews=['transcription_fidelity', 'speaker_and_listening', 'creative', 'model_and_output_rights'],
        scope='Same-byte waveform and provenance consistency only; supplied generation metadata is not authenticated')


def dispatch(job, upstream=None):
    require_disabled(job)
    if job.get('tool') != 'voicestudio':
        raise ValueError('Expected voicestudio tool')
    operation = job.get('operation')
    if operation == 'status':
        return result('voicestudio', operation,
            runtime_revision=RUNTIME_REVISION, reviewed_download_revision=REVIEWED_DOWNLOAD_REVISION,
            runtime_status='EXISTING_PIN_PRESERVED_NOT_PROBED',
            downloaded_revision_status='STATICALLY_REVIEWED_NOT_EXECUTED',
            supported_operations=['status', 'prepare-narration', 'validate-export'],
            blockers=['New downloaded revision has not been execution-approved or smoke-tested',
                      'Application AGPL terms and model/output rights require separate review',
                      'Default OmniVoice weights are marked non-commercial by upstream'],
            scope='Offline integration status; existing synthesize remains separately pinned')
    if operation not in ('prepare-narration', 'validate-export'):
        raise ValueError('Unsupported VoiceStudio review operation')
    data = read_json(job.get('input'))
    return prepare_narration(data) if operation == 'prepare-narration' else validate_export(data)
