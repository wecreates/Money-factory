"""Render fresh editorial scenes with offline Kokoro and original picture panels.

Technical completion leaves creative, factual and listening review open. This
renderer never changes canonical Episode 1 inputs or calls a publishing API.
"""
import argparse
from datetime import datetime, timezone
from collections import Counter
import difflib
import hashlib
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import sys
import time
import wave

VOICE_ASSIGNMENTS = {'dave': 'am_fenrir', 'points_monk': 'am_michael', 'narrator': 'am_adam'}
VOICE_TARGET_RMS = .075
VOICE_MAX_PEAK = .95
VOICE_LEGACY_MAX_GAIN = 1.8
VOICE_MAX_GAIN = 1.9
VOICE_LEGACY_LEVEL_ALGORITHM = 'bounded_isolated_narration_rms_v1'
VOICE_LEVEL_ALGORITHM = 'bounded_isolated_narration_rms_v2'
VOICE_LEVEL_SCOPE = ('Deterministic isolated-narration level matching only; direct full-mix listening '
                     'is still required for voice and sound acceptance.')
PCM_QUANTIZATION_TOLERANCE = 1 / 32767 + 1e-12
KINDS = {'card', 'receipt', 'balance', 'checklist', 'comparison'}
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
ASR_REPOSITORY = 'Systran/faster-whisper-base.en'
ASR_REVISION = '3d3d5dee26484f91867d81cb899cfcf72b96be6c'
ASR_ASSETS = {
    'config.json': (2227, 'f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb'),
    'model.bin': (145216508, '2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef'),
    'tokenizer.json': (2128466, '929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df'),
    'vocabulary.txt': (422309, 'ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf'),
}
MOTION_FRAMES = 24
MOTION_FPS = 8
MOTION_KIND = 'authored_scene_motion_v2'
MOTION_SCOPE = ('Deterministic three-second character motion. Existing scenes retain the periodic sway/bob; '
                'an opted scene can use one authored emphasis-and-hold pattern interrupt. Diagrams, typography, '
                'and speaker labels stay fixed. No lip sync or facial animation.')
AUTHORED_GESTURES = ('point_left', 'point_right', 'open_hands')
AUTHORED_MOTION_PATTERNS = ('emphasis_hold',)
PANEL_BACKGROUND = '#f7f1e6'
COMPARISON_BOUNDS = ((60, 340, 345, 710), (375, 340, 660, 710))
PORTRAIT_SIZE = (720, 1280)
PORTRAIT_ABOVE_LABEL_Y = 814
LANDSCAPE_SIZE = (1280, 720)
DIAGRAM_LAYER_TOP = 310
DIAGRAM_LAYER_BOTTOM = 811
LANDSCAPE_DIAGRAM_POSITION = (515, 129)
LANDSCAPE_CAPTION_SAFE_TOP = 526
LANDSCAPE_CONTENT_BOTTOM = 505


def panel_size(layout):
    if layout is None:
        return PORTRAIT_SIZE
    if layout == 'landscape':
        return LANDSCAPE_SIZE
    raise ValueError('Unsupported panel layout')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def editorial_digest(editorial):
    return hashlib.sha256(json.dumps(editorial, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')


def normalize_voice_samples(samples, *, target_rms=VOICE_TARGET_RMS,
                            peak_ceiling=VOICE_MAX_PEAK, max_gain=VOICE_MAX_GAIN):
    """Apply bounded deterministic level matching; never claim listening quality.

    Kokoro voices can have materially different generated levels for the same
    program.  Match each isolated narration clip to one conservative RMS target,
    while a hard peak ceiling and maximum boost prevent clipping or excessive
    amplification.  This is a signal-level repair only: direct full-mix
    listening remains required for naturalness, pronunciation and mix approval.
    """
    if (type(target_rms) not in (int, float) or not math.isfinite(target_rms)
            or not 0 < target_rms < 1):
        raise ValueError('Voice target RMS must be finite and between zero and one')
    if (type(peak_ceiling) not in (int, float) or not math.isfinite(peak_ceiling)
            or not 0 < peak_ceiling <= 1):
        raise ValueError('Voice peak ceiling must be finite and at most one')
    if (type(max_gain) not in (int, float) or not math.isfinite(max_gain)
            or not 1 <= max_gain <= 4):
        raise ValueError('Voice maximum gain must be finite from one through four')
    values = tuple(float(value) for value in samples)
    if not values or any(not math.isfinite(value) or abs(value) > 1 for value in values):
        raise ValueError('Invalid voice samples')
    source_rms = math.sqrt(sum(value * value for value in values) / len(values))
    source_peak = max(abs(value) for value in values)
    if source_rms < .001 or source_peak <= 0:
        raise ValueError('Silent generated narration')
    gain = min(target_rms / source_rms, peak_ceiling / source_peak, max_gain)
    normalized = tuple(value * gain for value in values)
    output_rms = math.sqrt(sum(value * value for value in normalized) / len(normalized))
    output_peak = max(abs(value) for value in normalized)
    evidence = {
        'algorithm': VOICE_LEVEL_ALGORITHM,
        'target_rms': target_rms,
        'peak_ceiling': peak_ceiling,
        'maximum_gain': max_gain,
        'source_rms': source_rms,
        'source_peak': source_peak,
        'applied_gain': gain,
        'output_rms': output_rms,
        'output_peak': output_peak,
        'listening_verified': False,
        'scope': VOICE_LEVEL_SCOPE,
    }
    return normalized, evidence


def wave_pcm_stats(path):
    """Measure exact bound PCM bytes and reject any alternate WAV contract."""
    try:
        with wave.open(str(path), 'rb') as pcm:
            if (pcm.getnchannels() != 1 or pcm.getsampwidth() != 2
                    or pcm.getframerate() != 24000 or pcm.getcomptype() != 'NONE'):
                raise ValueError('Narration WAV must be mono 16-bit 24kHz uncompressed PCM')
            frames = pcm.getnframes()
            if not 0 < frames <= 24000 * 90:
                raise ValueError('Invalid narration sample rate or duration')
            payload = pcm.readframes(frames)
    except wave.Error as error:
        raise ValueError('Invalid narration WAV') from error
    if len(payload) != frames * 2:
        raise ValueError('Narration WAV payload is incomplete')
    samples = struct.unpack('<' + 'h' * frames, payload)
    values = tuple(value / 32767 for value in samples)
    rms = math.sqrt(sum(value * value for value in values) / frames)
    peak = max(abs(value) for value in values)
    return {'frames': frames, 'duration_seconds': frames / 24000,
            'rms': rms, 'peak': peak}


def validate_voice_normalization(clip, wav_stats):
    """Revalidate the child receipt against exact WAV bytes before encoding."""
    value = clip.get('level_normalization')
    fields = {'algorithm', 'target_rms', 'peak_ceiling', 'maximum_gain',
              'source_rms', 'source_peak', 'applied_gain', 'output_rms',
              'output_peak', 'listening_verified', 'scope'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('Exact voice normalization receipt required')
    algorithm = value.get('algorithm')
    maximum_gain = {
        VOICE_LEGACY_LEVEL_ALGORITHM: VOICE_LEGACY_MAX_GAIN,
        VOICE_LEVEL_ALGORITHM: VOICE_MAX_GAIN,
    }.get(algorithm)
    if (maximum_gain is None
            or value.get('target_rms') != VOICE_TARGET_RMS
            or value.get('peak_ceiling') != VOICE_MAX_PEAK
            or value.get('maximum_gain') != maximum_gain
            or value.get('listening_verified') is not False
            or value.get('scope') != VOICE_LEVEL_SCOPE):
        raise ValueError('Voice normalization algorithm or scope changed')
    numeric = ('source_rms', 'source_peak', 'applied_gain', 'output_rms', 'output_peak')
    if any(type(value.get(name)) not in (int, float) or not math.isfinite(value[name])
           or value[name] <= 0 for name in numeric):
        raise ValueError('Voice normalization measurements must be finite and positive')
    if (not .001 <= value['source_rms'] <= value['source_peak'] <= 1):
        raise ValueError('Voice normalization source measurements are outside the accepted domain')
    expected_gain = min(VOICE_TARGET_RMS / value['source_rms'],
                        VOICE_MAX_PEAK / value['source_peak'], maximum_gain)
    if not math.isclose(value['applied_gain'], expected_gain, rel_tol=0, abs_tol=1e-12):
        raise ValueError('Voice normalization gain is inconsistent')
    for source, output in (('source_rms', 'output_rms'), ('source_peak', 'output_peak')):
        expected = value[source] * value['applied_gain']
        if not math.isclose(value[output], expected, rel_tol=0,
                            abs_tol=PCM_QUANTIZATION_TOLERANCE):
            raise ValueError('Voice normalization source and output measurements disagree')
    if value['output_peak'] > VOICE_MAX_PEAK + PCM_QUANTIZATION_TOLERANCE:
        raise ValueError('Voice normalization exceeded peak ceiling')
    if (not math.isclose(value['output_rms'], wav_stats['rms'], rel_tol=0,
                         abs_tol=PCM_QUANTIZATION_TOLERANCE)
            or not math.isclose(value['output_peak'], wav_stats['peak'], rel_tol=0,
                                abs_tol=PCM_QUANTIZATION_TOLERANCE)
            or type(clip.get('rms')) not in (int, float)
            or not math.isclose(clip['rms'], wav_stats['rms'], rel_tol=0,
                                abs_tol=PCM_QUANTIZATION_TOLERANCE)):
        raise ValueError('Voice normalization receipt does not match bound WAV')


def validate_visual_shape(spec):
    """Reject shapes whose fields the renderer cannot preserve; no normalization."""
    if not isinstance(spec, dict) or spec.get('kind', 'card') not in KINDS:
        raise ValueError('Invalid visual specification')
    if 'headline' in spec and (not isinstance(spec['headline'], str) or len(spec['headline']) > 60):
        raise ValueError('Invalid headline')
    if 'gesture' in spec and spec['gesture'] not in AUTHORED_GESTURES:
        raise ValueError('Gesture must be point_left, point_right or open_hands')
    if 'motion_pattern' in spec and spec['motion_pattern'] not in AUTHORED_MOTION_PATTERNS:
        raise ValueError('Motion pattern must be emphasis_hold')
    for key, limit in [('labels', 50), ('values', 30)]:
        fields = spec.get(key, [])
        if not isinstance(fields, list) or any(not isinstance(v, str) or len(v) > limit for v in fields):
            raise ValueError('Invalid visual ' + key)
    kind = spec.get('kind', 'card')
    labels, values = spec.get('labels', []), spec.get('values', [])
    if max(len(labels), len(values)) > 4:
        raise ValueError('Visual layouts support at most four fields')
    if kind in ('balance', 'comparison') and max(len(labels), len(values)) > 2:
        raise ValueError(kind + ': at most two fields; use card or receipt for more fields')
    if kind in ('balance', 'checklist') and labels and values:
        raise ValueError(kind + ': use labels or values, not both; use card, receipt or comparison for paired fields')
    reveal_keys = {'reveal_after_seconds', 'reveal_on_phrase'} & set(spec)
    if reveal_keys:
        if (kind != 'comparison' or len(labels) != 2 or len(values) != 2
                or any(not item.strip() for item in labels + values)):
            raise ValueError('Timed reveal requires two complete comparison cards')
        if len(reveal_keys) != 1:
            raise ValueError('Comparison reveal requires exactly one timing method')
    if 'reveal_after_seconds' in spec:
        offset = spec['reveal_after_seconds']
        if type(offset) not in (int, float) or not .25 <= offset <= 59.5:
            raise ValueError('Comparison reveal offset must be .25 to 59.5 scene-local seconds')
    if 'reveal_on_phrase' in spec:
        phrase = spec['reveal_on_phrase']
        if not isinstance(phrase, str) or not phrase.strip() or len(phrase) > 300:
            raise ValueError('Comparison reveal phrase must be 1 to 300 characters')


def validate(editorial):
    if not isinstance(editorial, dict) or editorial.get('publication_enabled') is not False:
        raise ValueError('Explicit disabled publication required')
    if any(editorial.get(key) is not False for key in ('production_approved', 'full_av_review')):
        raise ValueError('Explicit false production and audiovisual approval required')
    if editorial.get('paid_generation_enabled', False) is not False:
        raise ValueError('Paid generation forbidden')
    if 'layout' in editorial and editorial['layout'] != 'landscape':
        raise ValueError('layout: omit for portrait or set landscape')
    if 'speaker_label_position' in editorial and (editorial['speaker_label_position'] != 'above' or 'layout' in editorial):
        raise ValueError('speaker_label_position: omit or use above on portrait')
    scenes = editorial.get('scenes')
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 30:
        raise ValueError('One to thirty scenes required')
    seen = set()
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get('id'), str) or scene['id'] in seen:
            raise ValueError('Unique scene IDs required')
        seen.add(scene['id'])
        for key, limit in [('narration', 1000), ('visual', 1000)]:
            if not isinstance(scene.get(key), str) or not 1 <= len(scene[key].strip()) <= limit:
                raise ValueError('Invalid scene ' + key)
        if scene.get('speaker', 'narrator') not in VOICE_ASSIGNMENTS:
            raise ValueError('Unsupported voice assignment')
        spec = scene.get('visual_spec', {})
        validate_visual_shape(spec)
        if 'reveal_on_phrase' in spec:
            narration = scene['narration'].casefold()
            phrase = spec['reveal_on_phrase'].strip().casefold()
            if narration.count(phrase) != 1:
                raise ValueError('Comparison reveal phrase must occur exactly once in narration')
    return scenes


def run(command, log, deadline, env=None):
    from integrations.owned_process import owned_process
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Cycle render deadline exceeded')
    with Path(log).open('wb') as stream:
        with owned_process(list(map(str, command)), timeout=remaining, stdout=stream,
                           stderr=subprocess.STDOUT, env=env) as process:
            code = process.wait(timeout=remaining + 5)
    if code:
        raise RuntimeError(f'{Path(command[0]).name} failed; see {Path(log).name}')


def encoded_stream_sha256(media, stream, log, deadline):
    """Hash exact encoded packet payloads without decoding or remuxing them."""
    if stream not in ('v:0', 'a:0'):
        raise ValueError('Video or audio stream selector required')
    run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', Path(media),
         '-map', f'0:{stream}', '-c', 'copy', '-f', 'hash', '-hash', 'sha256', '-'],
        Path(log), deadline)
    match = re.fullmatch(r'SHA256=([0-9a-f]{64})\s*', Path(log).read_text())
    if match is None:
        raise ValueError('Encoded stream hash evidence is invalid')
    return match.group(1)


def normalize_mux_video_start(staged, output, deadline):
    """Remove concat's video-only lead-in without decoding either stream.

    The concat demuxer can retain the first AAC packet at zero while assigning
    the first H.264 presentation timestamp roughly one picture frame later.
    Timeline-bound excerpts would then begin on the preceding scene.  Offset a
    video-only input by the measured amount and take audio from an unshifted
    input so both encoded packet streams remain otherwise unchanged.
    """
    staged, output = Path(staged), Path(output)
    probe_path = output.parent / 'concat-probe.json'
    run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', staged],
        probe_path, deadline)
    probe = json.loads(probe_path.read_text())
    streams = probe.get('streams', [])
    video = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
    audio = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)
    if video is None or audio is None:
        raise ValueError('Concatenated media must contain video and audio')
    video_start = float(video.get('start_time', 'nan'))
    audio_start = float(audio.get('start_time', 'nan'))
    if (not math.isfinite(video_start) or not math.isfinite(audio_start)
            or not 0 <= video_start <= .1 or not 0 <= audio_start <= .1):
        raise ValueError('Concatenated stream start time is invalid')
    staged_file_sha256 = digest(staged)
    staged_streams = {
        'video': encoded_stream_sha256(staged, 'v:0', output.parent / 'streamhash-staged-video.log', deadline),
        'audio': encoded_stream_sha256(staged, 'a:0', output.parent / 'streamhash-staged-audio.log', deadline),
    }
    run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n', '-threads', '2',
         '-itsoffset', f'{-video_start:.9f}', '-i', staged, '-i', staged,
         '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', '-movflags', '+faststart', output],
        output.parent / 'normalize-start.log', deadline)
    normalized_streams = {
        'video': encoded_stream_sha256(output, 'v:0', output.parent / 'streamhash-normalized-video.log', deadline),
        'audio': encoded_stream_sha256(output, 'a:0', output.parent / 'streamhash-normalized-audio.log', deadline),
    }
    if digest(staged) != staged_file_sha256 or normalized_streams != staged_streams:
        output.unlink(missing_ok=True)
        raise ValueError('Timestamp normalization changed source bytes or encoded stream payloads')
    return {'staged_video_start_seconds': video_start,
            'staged_audio_start_seconds': audio_start,
            'encoded_streams_sha256': staged_streams,
            'mode': 'measured_video_offset_stream_copy'}


def synthesize(editorial, output, voice_root):
    """Runs in the isolated, pinned Kokoro runtime, with network denied."""
    scenes = validate(editorial)
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    def no_network(*args, **kwargs):
        raise RuntimeError('Network disabled during voice synthesis')
    socket.socket.connect = no_network
    generator = Path(voice_root).resolve() / 'scripts/v2_free_voice.py'
    spec = importlib.util.spec_from_file_location('cyzor_pinned_voice', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.VOICE_ASSIGNMENTS != VOICE_ASSIGNMENTS:
        raise ValueError('Voice assignment changed')
    generator_hash = digest(generator)
    synth = module.local_synthesizer()  # Verifies all five immutable model files.
    clips = []
    for index, scene in enumerate(scenes):
        speaker = scene.get('speaker', 'narrator')
        samples, rate = synth(scene['narration'], VOICE_ASSIGNMENTS[speaker], 1.0)
        if rate != 24000 or not 0 < len(samples) <= rate * 90:
            raise ValueError('Invalid voice output length')
        samples, normalization = normalize_voice_samples(samples)
        path = output / f'voice-{index:02d}.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            wav.writeframes(struct.pack('<' + 'h' * len(samples), *[round(float(v) * 32767) for v in samples]))
        actual = wave_pcm_stats(path)
        normalization.update(output_rms=actual['rms'], output_peak=actual['peak'])
        clips.append({'scene_id': scene['id'], 'speaker': speaker, 'voice_id': VOICE_ASSIGNMENTS[speaker],
                      'file': path.name, 'audio_sha256': digest(path), 'duration_seconds': len(samples) / rate,
                      'text_sha256': hashlib.sha256(scene['narration'].encode()).hexdigest(),
                      'rms': actual['rms'], 'level_normalization': normalization})
    if digest(generator) != generator_hash:
        raise ValueError('Voice generator changed during synthesis')
    write(output / 'voice.json', {'status': 'GENERATED_PENDING_LISTENING_REVIEW', 'clips': clips,
          'generator_sha256': generator_hash, **module.model_identity(), 'publication_enabled': False,
          'paid_generation_enabled': False, 'production_approved': False, 'full_av_review': False,
          'voice_assignments': VOICE_ASSIGNMENTS})


def character_motion(spec, phase):
    """Return deterministic character translation and arm emphasis for one scene.

    The default exactly preserves the original periodic sway/bob. The authored
    emphasis pattern introduces a still opening, a short eased move, a sustained
    hold, and an eased return. It is deliberately opt-in so old editorials and
    their character identities remain unchanged.
    """
    if type(phase) not in (int, float) or not math.isfinite(phase):
        raise ValueError('Finite numeric motion phase required')
    normalized = phase % 1.0
    if spec.get('motion_pattern') != 'emphasis_hold':
        wave = math.sin(2 * math.pi * normalized)
        return round(wave * 18), -round(abs(wave) * 10), wave * .18
    if normalized < .2:
        emphasis = 0.0
    elif normalized < .32:
        progress = (normalized - .2) / .12
        emphasis = progress * progress * (3 - 2 * progress)
    elif normalized < .72:
        emphasis = 1.0
    else:
        progress = (1 - normalized) / .28
        emphasis = progress * progress * (3 - 2 * progress)
    direction = -1 if spec.get('gesture') == 'point_left' else 1
    return round(direction * emphasis * 22), -round(emphasis * 8), emphasis * .2


def draw_panel(scene, path, index, count, phase=0.0, *, layout=None, speaker_label_position=None):
    """Fresh diagram and character composition with bounded authored motion.

    Phase is a fraction of one loop. Zero preserves the representative pose;
    labels, diagrams and identity stay fixed for every supported motion pattern.
    """
    size = panel_size(layout)
    if speaker_label_position is not None and (speaker_label_position != 'above' or layout is not None):
        raise ValueError('speaker_label_position: omit or use above on portrait')
    validate_visual_shape(scene.get('visual_spec', {}))
    spec = scene.get('visual_spec', {})
    x_offset, y_offset, gesture = character_motion(spec, phase)
    from PIL import Image, ImageDraw, ImageFont
    # The shared diagram layer preserves existing labels, artwork and font bounds.
    image = Image.new('RGB', (PORTRAIT_SIZE[0], DIAGRAM_LAYER_BOTTOM) if layout else size,
                      PANEL_BACKGROUND)
    draw = ImageDraw.Draw(image)
    ink, accent = '#141414', '#007f89'
    def font(size):
        return ImageFont.truetype(FONT, size)
    def wrapped(text, y, size=38, width=600, color=ink, max_lines=4, center=360):
        f = font(size)
        words, lines, current = str(text).split(), [], ''
        for word in words:
            trial = (current + ' ' + word).strip()
            if draw.textlength(trial, font=f) > width and current:
                lines.append(current); current = word
            else:
                current = trial
        if current: lines.append(current)
        if len(lines) > max_lines or any(draw.textlength(line, font=f) > width for line in lines):
            raise ValueError('Visual text exceeds readable panel bounds')
        for line in lines:
            draw.text((center, y), line, font=f, fill=color, anchor='mt')
            y += size + 12
        return y
    def bounded_text(text, box, *, sizes=(30, 28, 24, 22, 20), color=ink, left_aligned=False):
        """Wrap one semantic field inside its own region; never clip or omit it."""
        left, top, right, bottom = box
        for size in sizes:
            f = font(size)
            lines, current = [], ''
            for word in str(text).split():
                trial = (current + ' ' + word).strip()
                if draw.textlength(trial, font=f) > right-left and current:
                    lines.append(current); current = word
                else:
                    current = trial
            if current: lines.append(current)
            line_height = size + 4
            if (len(lines)*line_height <= bottom-top and
                    all(draw.textlength(line, font=f) <= right-left for line in lines)):
                y = top + (bottom-top-len(lines)*line_height)/2
                x, anchor = (left, 'lt') if left_aligned else ((left+right)/2, 'mt')
                positions = [(x, y + index * line_height) for index in range(len(lines))]
                bounds = [draw.textbbox(position, line, font=f, anchor=anchor)
                          for position, line in zip(positions, lines)]
                if left_aligned and bounds:
                    inset = max(0, left - min(a for a, _, _, _ in bounds))
                    positions = [(px + inset, py) for px, py in positions]
                    bounds = [(a + inset, b, c + inset, d) for a, b, c, d in bounds]
                if any(a < left or b < top or c > right or d > bottom for a, b, c, d in bounds):
                    continue
                for position, line in zip(positions, lines):
                    draw.text(position, line, font=f, fill=color, anchor=anchor)
                return
        raise ValueError('Visual text exceeds readable panel bounds')
    headline = spec.get('headline') or scene['visual'][:60]
    if layout is None:
        wrapped(headline, 105, size=42, max_lines=3)
    kind = spec.get('kind', 'card')
    labels, values = spec.get('labels', []), spec.get('values', [])
    if kind == 'balance':
        draw.line((360, 390, 360, 750), fill=ink, width=10)
        draw.line((130, 450, 590, 450), fill=ink, width=10)
        draw.line((280, 750, 440, 750), fill=ink, width=12)
        for x in (180, 540):
            draw.line((x, 450, x-70, 590), fill=ink, width=5)
            draw.line((x, 450, x+70, 590), fill=ink, width=5)
            draw.arc((x-80, 535, x+80, 645), 0, 180, fill=accent, width=9)
        wrapped('  |  '.join(values[:2] or labels[:2]), 660, size=36, max_lines=2)
    elif kind == 'comparison':
        if max(len(labels), len(values)) > 2:
            raise ValueError('Comparison supports at most two labeled fields')
        for i, bounds in enumerate(COMPARISON_BOUNDS):
            x = bounds[0]
            color = accent if i else ink
            draw.rounded_rectangle(bounds, radius=24, outline=color, width=6)
            if i < len(labels):
                # A label belongs to its own card, including label-only comparisons.
                box = (x+16, 370, x+269, 460) if i < len(values) else (x+16, 405, x+269, 645)
                bounded_text(labels[i], box, color=color)
            if i < len(values):
                bounded_text(values[i], (x+16, 480, x+269, 660), sizes=(34, 30, 28, 25), color=color)
    elif kind == 'checklist':
        draw.rounded_rectangle((80, 320, 640, 790), radius=20, outline=ink, width=5)
        for i, label in enumerate((labels or values)[:4]):
            y = 365+i*95
            draw.line((110,y+15,125,y+30,150,y-5),fill=accent,width=7)
            f=font(24)
            if draw.textlength(label,font=f)>430: f=font(19)
            if draw.textlength(label,font=f)<=430:
                draw.text((175,y),label,font=f,fill=ink)
            else:
                bounded_text(label, (175, y-8, 605, y+56), sizes=(24, 22, 19), left_aligned=True)
    else:
        draw.rounded_rectangle((85, 335, 635, 760), radius=18 if kind=='receipt' else 38, outline=ink, width=7)
        if kind == 'card':
            draw.rounded_rectangle((120, 375, 195, 430), radius=8, outline=accent, width=5)
        count_fields = max(len(labels), len(values), 1)
        if count_fields > 4:
            raise ValueError('Card and receipt support at most four labeled fields')
        top = 455 if kind == 'card' else 350
        row_height = (740-top)/count_fields
        for i in range(count_fields):
            y = top+i*row_height
            has_label, has_value = i < len(labels), i < len(values)
            if has_label and has_value:
                split = y+row_height*(.5 if kind == 'card' else .55)
                bounded_text(labels[i], (105, y+3, 615, split-2), color=ink)
                bounded_text(values[i], (105, split+2, 615, y+row_height-3), sizes=(40, 34, 30, 26, 24), color=accent)
            else:
                text = labels[i] if has_label else values[i] if has_value else 'THE REAL COST'
                bounded_text(text, (105, y+3, 615, y+row_height-3), sizes=(40, 34, 30, 26, 24))
            if i+1 < count_fields:
                draw.line((110, y+row_height, 610, y+row_height), fill=ink, width=1)
    if layout == 'landscape':
        # Landscape used to paste the lower 501 pixels of the portrait diagram at
        # y=129.  That put authored labels and the speaker name into y>=526, the
        # conservative sidecar-caption region used by the review pipeline.  Draw
        # a purpose-built landscape information panel instead: the type remains
        # at its native font size and all authored content ends above y=526.
        stage = Image.new('RGB', size, PANEL_BACKGROUND)
        image = stage
        draw = ImageDraw.Draw(image)
        wrapped(headline, 32, size=42, width=970, max_lines=2, center=640)
        left, top, right, bottom = 510, 126, 1220, LANDSCAPE_CONTENT_BOTTOM
        if kind == 'comparison':
            if max(len(labels), len(values)) > 2:
                raise ValueError('Comparison supports at most two labeled fields')
            cards = ((left, top, 850, bottom), (880, top, right, bottom))
            for i, bounds in enumerate(cards):
                color = accent if i else ink
                draw.rounded_rectangle(bounds, radius=24, outline=color, width=6)
                if i < len(labels):
                    label_bottom = 285 if i < len(values) else bottom - 20
                    bounded_text(labels[i], (bounds[0]+18, top+24, bounds[2]-18, label_bottom),
                                 sizes=(36, 32, 30, 28), color=color)
                if i < len(values):
                    bounded_text(values[i], (bounds[0]+18, 300, bounds[2]-18, bottom-18),
                                 sizes=(38, 34, 32, 30), color=color)
        elif kind == 'checklist':
            draw.rounded_rectangle((left, top, right, bottom), radius=20, outline=ink, width=5)
            items = (labels or values)[:4]
            row_height = (bottom-top-24)/max(len(items), 1)
            for i, label in enumerate(items):
                y = top+12+i*row_height
                draw.line((left+30, y+row_height*.52, left+47, y+row_height*.68,
                           left+78, y+row_height*.24), fill=accent, width=7)
                bounded_text(label, (left+105, y+4, right-24, y+row_height-4),
                             sizes=(34, 32, 30, 28), left_aligned=True)
        elif kind == 'balance':
            draw.line((865, 180, 865, 425), fill=ink, width=10)
            draw.line((610, 225, 1120, 225), fill=ink, width=10)
            draw.line((780, 425, 950, 425), fill=ink, width=12)
            for x in (660, 1070):
                draw.line((x, 225, x-75, 350), fill=ink, width=5)
                draw.line((x, 225, x+75, 350), fill=ink, width=5)
                draw.arc((x-85, 315, x+85, 430), 0, 180, fill=accent, width=9)
            bounded_text('  |  '.join(values[:2] or labels[:2]),
                         (left+20, 435, right-20, bottom), sizes=(34, 32, 30))
        else:
            draw.rounded_rectangle((left, top, right, bottom),
                                   radius=18 if kind == 'receipt' else 38,
                                   outline=ink, width=7)
            count_fields = max(len(labels), len(values), 1)
            if count_fields > 4:
                raise ValueError('Card and receipt support at most four labeled fields')
            inner_top = top+18
            if kind == 'card':
                draw.rounded_rectangle((left+28, top+24, left+105, top+80),
                                       radius=8, outline=accent, width=5)
                inner_top = top+92
            row_height = (bottom-inner_top-12)/count_fields
            for i in range(count_fields):
                y = inner_top+i*row_height
                has_label, has_value = i < len(labels), i < len(values)
                if has_label and has_value:
                    split = y+row_height*.5
                    bounded_text(labels[i], (left+24, y+2, right-24, split-1),
                                 sizes=(32, 30, 28))
                    bounded_text(values[i], (left+24, split+1, right-24, y+row_height-2),
                                 sizes=(36, 34, 32, 30), color=accent)
                else:
                    field = labels[i] if has_label else values[i] if has_value else 'THE REAL COST'
                    bounded_text(field, (left+24, y+2, right-24, y+row_height-2),
                                 sizes=(36, 34, 32, 30))
                if i+1 < count_fields:
                    draw.line((left+24, y+row_height, right-24, y+row_height), fill=ink, width=1)
    # Recurring character silhouette. Direction is visible above, not misreported
    # as an AI-generated image. Three poses vary between scenes.
    base_x,base_y=(250,320) if layout == 'landscape' else (360,970)
    # Moving the complete silhouette, rather than only a few arm pixels, keeps
    # the picture visibly alive at phone size while leaving the information
    # layer and speaker identity anchored.  The loop starts and ends on the
    # exact representative pose, so panel receipts remain deterministic.
    x = base_x + x_offset
    y = base_y + y_offset
    draw.ellipse((x-38,y-100,x+38,y-24),outline=ink,width=6)
    draw.ellipse((x-16,y-76,x-9,y-69),fill=ink)
    draw.ellipse((x+9,y-76,x+16,y-69),fill=ink)
    draw.line((x-10,y-48,x+12,y-48),fill=ink,width=4)
    draw.line((x,y-24,x,y+80),fill=ink,width=7)
    pose=index%3
    arms = ((-65, 25 if pose else -35, gesture), (65, -45 if pose else 25, -gesture))
    authored = spec.get('gesture')
    if authored == 'point_left':
        arms = ((-69, -59, gesture), (43, 58, 0))
    elif authored == 'point_right':
        arms = ((-43, 58, 0), (69, -59, -gesture))
    elif authored == 'open_hands':
        arms = ((-79, -16, gesture), (79, -16, -gesture))
    for dx, dy, angle in arms:
        # Rotate fixed-length arms about the shoulders, rather than stretching.
        hand_x = x + round(dx * math.cos(angle) - dy * math.sin(angle))
        hand_y = y + 10 + round(dx * math.sin(angle) + dy * math.cos(angle))
        draw.line((x,y+10,hand_x,hand_y),fill=ink,width=7)
    draw.line((x,y+80,x-45,y+140),fill=ink,width=7)
    draw.line((x,y+80,x+45,y+140),fill=ink,width=7)
    speaker=scene.get('speaker','narrator').replace('_',' ').upper()
    label_y = PORTRAIT_ABOVE_LABEL_Y if speaker_label_position == 'above' else base_y+160
    label_size = 34 if layout == 'landscape' else 23
    draw.text((base_x,label_y),speaker,font=font(label_size),fill=accent,anchor='mt')
    draw.text((size[0]-60, 22 if layout == 'landscape' else 50),
              f'{index+1}/{count}',font=font(22),fill=ink,anchor='rt')
    image.save(path)


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    h, rem = divmod(milliseconds, 3600000); m, rem = divmod(rem, 60000); s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'


def picture_filters(scene, frame_count, layout=None, narration_duration=None):
    width, height = panel_size(layout)
    filters = f'scale={width}:{height},setsar=1,fps=24'
    spec = scene.get('visual_spec', {})
    offset = spec.get('reveal_after_seconds')
    phrase = spec.get('reveal_on_phrase')
    if offset is None and phrase is None:
        return filters, None
    timing = {'alignment_method': 'explicit_scene_offset'}
    if phrase is not None:
        if type(narration_duration) not in (int, float) or not math.isfinite(narration_duration) \
                or narration_duration <= 0:
            raise ValueError('Phrase reveal requires measured narration duration')
        narration = scene['narration']
        start = narration.casefold().find(phrase.strip().casefold())
        if start < 0 or narration.casefold().count(phrase.strip().casefold()) != 1:
            raise ValueError('Comparison reveal phrase must occur exactly once in narration')
        offset = narration_duration * start / len(narration)
        timing = {'alignment_method': 'measured_duration_character_fraction',
                  'requested_phrase': phrase.strip(),
                  'phrase_character_offset': start,
                  'narration_characters': len(narration)}
    frame = math.ceil(offset * 24)
    if frame_count - frame < 12:
        raise ValueError('Comparison reveal requires half a second of rendered screen time')
    left, top, right, bottom = COMPARISON_BOUNDS[1]
    if layout == 'landscape':
        left, top, right, bottom = 880, 126, 1220, LANDSCAPE_CONTENT_BOTTOM
    # The filter runs on the complete 24 fps scene, outside the repeating arm loop.
    filters += (f",drawbox=x={left}:y={top}:w={right-left+1}:h={bottom-top+1}"
                f":color=0x{PANEL_BACKGROUND[1:]}:t=fill:enable='lt(n,{frame})'")
    return filters, {'kind': 'second_comparison_card', 'requested_offset_seconds': offset,
                     'first_visible_scene_frame': frame, 'rendered_offset_seconds': frame / 24,
                     **timing}


def measured_clip_frames(scenes, voice, output):
    """Check the exact narration and compute the 24 fps frame budget before encoding."""
    if (not isinstance(voice, dict)
            or voice.get('status') != 'GENERATED_PENDING_LISTENING_REVIEW'
            or voice.get('voice_assignments') != VOICE_ASSIGNMENTS
            or any(voice.get(field) is not False for field in
                   ('publication_enabled', 'paid_generation_enabled',
                    'production_approved', 'full_av_review'))):
        raise ValueError('Exact pending-listening voice receipt contract required')
    clips = voice.get('clips')
    if not isinstance(clips, list):
        raise ValueError('Voice clips must be a list')
    if len(clips) != len(scenes):
        raise ValueError('Missing voice clips')
    frames = []
    for index, (scene, clip) in enumerate(zip(scenes, clips)):
        wav = output / f'voice-{index:02d}.wav'
        speaker = scene.get('speaker', 'narrator')
        if (not isinstance(clip, dict)
                or clip.get('scene_id') != scene['id']
                or clip.get('speaker') != speaker
                or clip.get('voice_id') != VOICE_ASSIGNMENTS[speaker]
                or clip.get('file') != wav.name
                or clip.get('audio_sha256') != digest(wav)
                or clip.get('text_sha256') != hashlib.sha256(scene['narration'].encode()).hexdigest()):
            raise ValueError('Narration binding mismatch')
        stats = wave_pcm_stats(wav)
        validate_voice_normalization(clip, stats)
        duration = stats['duration_seconds']
        if clip['duration_seconds'] != duration:
            raise ValueError('Narration duration does not match WAV')
        frames.append(math.ceil((duration + .28) * 24))
    return frames


def render_cycle(editorial, output, *, voice_python, voice_root, timeout=900, transcription_python=None,
                 minimum_duration=None, maximum_duration=None):
    scenes = validate(editorial)
    layout = editorial.get('layout')
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0 < timeout <= 1800:
        raise ValueError('Render timeout must be positive and at most 1800 seconds')
    if minimum_duration is not None and (type(minimum_duration) is not int or not 1 <= minimum_duration <= 600):
        raise ValueError('Minimum duration must be an integer from 1 to 600 seconds')
    if maximum_duration is not None and (type(maximum_duration) is not int or not 1 <= maximum_duration <= 600):
        raise ValueError('Maximum duration must be an integer from 1 to 600 seconds')
    if minimum_duration is not None and maximum_duration is not None and minimum_duration > maximum_duration:
        raise ValueError('Minimum duration cannot exceed maximum duration')
    if os.environ.get('PUBLICATION_ENABLED','false').lower()!='false':
        raise ValueError('Publication must remain disabled')
    runtime = Path(voice_python)
    if not runtime.is_absolute() or not runtime.is_file() or not os.access(runtime,os.X_OK):
        raise ValueError('Absolute executable voice runtime required')
    if transcription_python:
        asr_runtime = Path(transcription_python)
        if not asr_runtime.is_absolute() or not asr_runtime.is_file() or not os.access(asr_runtime,os.X_OK):
            raise ValueError('Absolute executable transcription runtime required')
    output = Path(output).absolute(); output.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':1,'status':'BLOCKED','technical_status':'PENDING',
             'publication_enabled':False,'paid_generation_enabled':False,'production_approved':False,
             'full_av_review':False,'editorial_sha256':editorial_digest(editorial),
             'started_at':datetime.now(timezone.utc).isoformat(),
             'scope':'Fresh offline speech and original diagram-based picture video; technical verification only.',
             'motion':{'kind':MOTION_KIND,'frame_count':MOTION_FRAMES,
                       'source_fps':MOTION_FPS,'loop_seconds':MOTION_FRAMES/MOTION_FPS,
                       'output_fps':24,'scope':MOTION_SCOPE}}
    if layout:
        receipt['layout'] = layout
    if layout == 'landscape':
        receipt['authored_content_bounds'] = {
            'caption_safe_top': LANDSCAPE_CAPTION_SAFE_TOP,
            'content_bottom': LANDSCAPE_CONTENT_BOTTOM,
            'speaker_label_font_size': 34,
            'secondary_field_minimum_font_size': 28,
            'scope': ('Renderer-authored headline, diagrams, values, character and speaker label; '
                      'burned or sidecar caption glyphs are not included.'),
        }
    panel_options = {'layout': layout}
    if 'speaker_label_position' in editorial:
        panel_options['speaker_label_position'] = editorial['speaker_label_position']
        receipt['speaker_label_position'] = editorial['speaker_label_position']
    if minimum_duration is not None:
        receipt['minimum_duration_seconds'] = minimum_duration
    if maximum_duration is not None:
        receipt['maximum_duration_seconds'] = maximum_duration
    deadline=time.monotonic()+timeout
    write(output/'render.json',receipt); write(output/'editorial.json',editorial)
    try:
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PUBLICATION_ENABLED='false',
                 OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
        run([runtime,Path(__file__).resolve(),'--synthesize','--editorial',output/'editorial.json',
             '--output',output,'--voice-root',Path(voice_root).resolve()],output/'voice.log',deadline,env)
        voice=json.loads((output/'voice.json').read_text())
        clips=voice['clips']
        frames = measured_clip_frames(scenes, voice, output)
        planned_frames = sum(frames)
        if planned_frames > 600 * 24:
            raise ValueError('Video exceeds ten minute limit')
        if minimum_duration is not None or maximum_duration is not None:
            receipt['measured_narration_frame_budget'] = planned_frames
        if minimum_duration is not None and planned_frames < minimum_duration * 24:
            raise ValueError(f'Measured narration budgets {planned_frames / 24:.3f}s of video, below {minimum_duration}s minimum')
        if maximum_duration is not None and planned_frames > maximum_duration * 24:
            raise ValueError(f'Measured narration budgets {planned_frames / 24:.3f}s of video, above {maximum_duration}s maximum')
        rows=[]; captions=['WEBVTT','']; start=0; segments=[]
        for index,(scene,clip,frame_count) in enumerate(zip(scenes,clips,frames)):
            wav=output/f'voice-{index:02d}.wav'
            if clip['audio_sha256']!=digest(wav):
                raise ValueError('Narration binding mismatch')
            duration=frame_count/24
            filters, reveal = picture_filters(scene, frame_count, layout, clip['duration_seconds'])
            panel=output/f'panel-{index:02d}.png'; draw_panel(scene,panel,index,len(scenes),**panel_options)
            motion_dir=output/f'motion-{index:02d}'; motion_dir.mkdir()
            motion_hashes={}
            for frame_index in range(MOTION_FRAMES):
                if time.monotonic() >= deadline: raise TimeoutError('Cycle render deadline exceeded during motion frames')
                frame=motion_dir/f'frame-{frame_index:02d}.png'
                if frame_index == 0:
                    frame.write_bytes(panel.read_bytes())
                else:
                    draw_panel(scene,frame,index,len(scenes),phase=frame_index/MOTION_FRAMES,**panel_options)
                motion_hashes[frame.name]=digest(frame)
            segment=output/f'segment-{index:02d}.mp4'
            run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-threads','2',
                 '-stream_loop','-1','-framerate',str(MOTION_FPS),'-start_number','0',
                 '-i',motion_dir/'frame-%02d.png','-i',wav,'-t',f'{duration:.6f}',
                 '-vf',filters,'-af','apad','-c:v','libx264','-preset','veryfast',
                 '-crf','20','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','24000','-ac','1',
                 '-movflags','+faststart',segment],output/f'encode-{index:02d}.log',deadline)
            # Caption groups are evenly timed within the measured clip. They are
            # explicitly approximate until independent ASR alignment is supplied.
            words=scene['narration'].split();groups=[words[i:i+7] for i in range(0,len(words),7)]
            for i,group in enumerate(groups):
                a=start+clip['duration_seconds']*i/len(groups);b=start+clip['duration_seconds']*(i+1)/len(groups)
                captions.extend([f'{timestamp(a)} --> {timestamp(b)}',html.escape(' '.join(group)),''])
            rows.append({'scene_id':scene['id'],'start':start,'end':start+duration,
                         'narration_end':start+clip['duration_seconds'],'panel':panel.name,
                         'panel_sha256':digest(panel),'voice_sha256':digest(wav),'segment_sha256':digest(segment),
                         'motion_directory':motion_dir.name,'motion_frames_sha256':motion_hashes})
            if 'gesture' in scene.get('visual_spec', {}):
                rows[-1]['authored_gesture'] = scene['visual_spec']['gesture']
            if 'motion_pattern' in scene.get('visual_spec', {}):
                rows[-1]['authored_motion_pattern'] = scene['visual_spec']['motion_pattern']
            if reveal:
                rows[-1]['visual_reveal'] = reveal
                receipt['motion']['scope'] = (MOTION_SCOPE + ' Opted comparison scenes reveal the second card once '
                                             'on the rendered scene clock; no automatic speech alignment.')
            segments.append(segment.name);start+=duration
        (output/'segments.txt').write_text(''.join("file '"+name+"'\n" for name in segments))
        staged_video = output/'concatenated.mp4'
        run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-f','concat','-safe','1',
             '-i',output/'segments.txt','-c','copy','-movflags','+faststart',staged_video],output/'concat.log',deadline)
        timestamp_normalization = normalize_mux_video_start(staged_video, output/'video.mp4', deadline)
        staged_video.unlink()
        (output/'captions.vtt').write_text('\n'.join(captions)+'\n')
        run(['ffmpeg','-nostdin','-v','error','-i',output/'video.mp4','-f','null','-'],output/'decode.log',deadline)
        run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',output/'video.mp4'],output/'probe.json',deadline)
        probe=json.loads((output/'probe.json').read_text());streams=probe['streams']
        video=next(s for s in streams if s['codec_type']=='video');audio=next(s for s in streams if s['codec_type']=='audio')
        if (video['width'],video['height'],video['codec_name'],audio['codec_name'])!=(*panel_size(layout),'h264','aac'):
            raise ValueError('Output media contract mismatch')
        normalized_video_start = float(video.get('start_time', 'nan'))
        normalized_audio_start = float(audio.get('start_time', 'nan'))
        if (not math.isfinite(normalized_video_start) or not math.isfinite(normalized_audio_start)
                or abs(normalized_video_start) > .001 or abs(normalized_audio_start) > .001):
            raise ValueError('Output stream timestamps were not normalized to zero')
        timestamp_normalization.update(video_start_seconds=normalized_video_start,
                                       audio_start_seconds=normalized_audio_start)
        receipt['timestamp_normalization'] = timestamp_normalization
        container_duration = float(probe['format']['duration'])
        if abs(container_duration-start)>.25:
            raise ValueError('Output duration differs from scene timeline')
        if minimum_duration is not None or maximum_duration is not None:
            from integrations.content_control.cycle_package import picture_duration
            duration = picture_duration(video)
            receipt['encoded_picture_duration_seconds'] = float(duration)
            if minimum_duration is not None and duration < minimum_duration:
                raise ValueError(f'Encoded picture duration {float(duration):.3f}s is below {minimum_duration}s minimum')
            if maximum_duration is not None:
                receipt['encoded_container_duration_seconds'] = container_duration
                if not 0 < duration <= maximum_duration or not 0 < container_duration <= maximum_duration:
                    raise ValueError(f'Encoded picture or container exceeds {maximum_duration}s maximum')
        write(output/'timeline.json',{'scenes':rows,'duration_seconds':start,'publication_enabled':False})
        asr=None
        if transcription_python:
            timeline_sha = digest(output/'timeline.json')
            asr_env=dict(env,HF_HOME=os.environ.get('CYZOR_ASR_HF_HOME',str(Path.home()/'.cache/huggingface')))
            run([transcription_python,Path(__file__).resolve(),'--transcribe','--editorial',output/'editorial.json',
                 '--output',output,'--voice-root',Path(voice_root).resolve(),'--timeline',output/'timeline.json'],
                output/'transcription.log',deadline,asr_env)
            asr=json.loads((output/'transcription.json').read_text())
            if (asr.get('status')!='PASS' or asr.get('candidate_sha256')!=digest(output/'video.mp4')
                    or asr.get('editorial_sha256')!=editorial_digest(editorial)
                    or asr.get('caption_sha256')!=digest(output/'captions.vtt')
                    or asr.get('timeline_sha256')!=timeline_sha
                    or digest(output/'timeline.json')!=timeline_sha):
                raise ValueError('Encoded transcription receipt identity mismatch')
        receipt.update(status='AWAITING_REVIEW',technical_status='PASS',candidate_sha256=digest(output/'video.mp4'),
                       caption_sha256=digest(output/'captions.vtt'),voice_receipt_sha256=digest(output/'voice.json'),
                       timeline_sha256=digest(output/'timeline.json'),duration_seconds=container_duration,
                       scenes=rows,caption_timing='observed_word_timestamps' if asr else 'approximate_groups_over_measured_speech',
                       independent_transcription_verified=bool(asr),voice_model=voice['model_revision'])
        if asr: receipt['transcription_receipt_sha256']=digest(output/'transcription.json')
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,EOFError,wave.Error,ZeroDivisionError,subprocess.TimeoutExpired,TimeoutError) as error:
        receipt.update(status='BLOCKED',technical_status='FAIL',reason=str(error))
    finally:
        receipt['finished_at']=datetime.now(timezone.utc).isoformat();write(output/'render.json',receipt)
    return receipt


def compare_transcription(expected, actual, normalize):
    """Strict ordered comparison plus exact numeric/negation tokens.

    Expected narration is consumed only after independent recognition; never
    used as a recognizer prompt. Ordered critical tokens reject swapped numbers,
    but this lexical check does not certify semantic equivalence or naturalness.
    """
    expected_words, actual_words = normalize(expected).split(), normalize(actual).split()
    ratio = difflib.SequenceMatcher(None, expected_words, actual_words, autojunk=False).ratio()
    ec, ac = Counter(expected_words), Counter(actual_words)
    recall = sum(min(v, ac[k]) for k, v in ec.items()) / max(1, len(expected_words))
    critical = set(('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion trillion dollar cent percent minus plus point not never no cannot without').split())
    def critical_sequence(words):
        return [word for word in words if word in critical or any(character.isdigit() for character in word)]
    critical_match = critical_sequence(expected_words) == critical_sequence(actual_words)
    return {'ordered_word_similarity': ratio, 'word_recall': recall,
            'critical_numeric_and_negation_tokens_match': critical_match,
            'passed': bool(expected_words) and ratio >= .96 and recall >= .96 and critical_match}


def _caption_sentence_end(text):
    """Conservative English ASR punctuation heuristic, not a sentence parser."""
    token = text.strip().rstrip('"\'’”)]}')
    if token.endswith(('!', '?')):
        return True
    if not token.endswith('.'):
        return False
    if token.lower() in {'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.',
                         'st.', 'vs.', 'etc.', 'e.g.', 'i.e.', 'no.', 'fig.',
                         'approx.', 'inc.', 'ltd.'}:
        return False
    # Initials and dotted acronyms (A., U.S.) are ambiguous; do not force a split.
    parts = token[:-1].split('.')
    return not all(len(part) == 1 and part.isalpha() for part in parts)


def caption_display_words(words, recognized_text, *, scene_boundaries=()):
    """Rejoin recognizer-confirmed hyphen compounds for caption display only.

    Faster Whisper can expose ``three-year`` in recognized segment text while
    returning two timed words, ``three`` and ``-year``. A plain space join then
    manufactures ``three -year`` and can split the suffix into a later cue.
    Rejoin only when the complete timed-word character stream aligns to the
    independent recognized text and the source characters at this boundary are
    adjacent. Raw ASR words remain unchanged in the transcription report.
    """
    if not isinstance(recognized_text, str):
        raise ValueError('Recognized caption text required')
    if not isinstance(scene_boundaries, (tuple, list)):
        raise ValueError('Caption scene boundaries must be a sequence')
    tokens = [''.join(word['word'].split()) for word in words]
    source = [(character, index) for index, character in enumerate(recognized_text)
              if not character.isspace()]
    if ''.join(tokens) != ''.join(character for character, _ in source):
        return [dict(word) for word in words], []
    offsets = []
    position = 0
    for token in tokens:
        offsets.append(position)
        position += len(token)
    display = []
    joins = []
    index = 0
    while index < len(words):
        current = words[index]
        if index + 1 < len(words):
            following = words[index + 1]
            left, right = tokens[index], tokens[index + 1]
            left_raw = ' '.join(current['word'].split())
            right_raw = ' '.join(following['word'].split())
            boundary = offsets[index] + len(left)
            candidate = left + right
            gap = following['start'] - current['end']
            span_end = max(current['end'], following['end'])
            source_adjacent = (boundary > 0 and boundary < len(source)
                               and source[boundary][1] == source[boundary - 1][1] + 1)
            crosses_scene = any(current['start'] < marker < span_end
                                for marker in scene_boundaries)
            if (source_adjacent and left_raw == left and right_raw == right
                    and re.fullmatch(r'[A-Za-z]+', left)
                    and re.fullmatch(r'-[A-Za-z]+(?:[.!?])?', right)
                    and -.02 <= gap <= .02 and following['end'] >= current['end']
                    and not crosses_scene):
                merged = dict(current)
                merged.update(word=candidate, end=span_end)
                display.append(merged)
                joins.append({'left': left, 'right': right, 'display': candidate,
                              'start': current['start'], 'end': span_end})
                index += 2
                continue
        display.append(dict(current))
        index += 1
    return display, joins


class ObservedWordTimingError(ValueError):
    """Rejected raw observation location; never a license to retime it."""
    def __init__(self, index, reason, previous_end, duration):
        super().__init__(f'Invalid observed word timing at index {index}: {reason}')
        self.diagnostic = {'word_index': index, 'reason': reason,
                           'previous_end': previous_end, 'encoded_media_duration_seconds': duration}


def write_transcription_report(path, report):
    """Persist rejected nonfinite numbers explicitly without invalid JSON.

    Finite observations remain unchanged. Tags retain otherwise unserializable
    values for diagnosis and are never passed to the caption validator as time.
    """
    def diagnostic_value(value):
        if type(value) is float and not math.isfinite(value):
            return {'nonfinite_float': 'nan' if math.isnan(value) else ('inf' if value > 0 else '-inf')}
        if isinstance(value, dict):
            return {key: diagnostic_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [diagnostic_value(item) for item in value]
        return value
    write(path, diagnostic_value(report))


def observed_captions(words, duration, *, scene_boundaries=()):
    """Group observed words at punctuation/0.5s pauses, with a seven-word cap.

    This heuristic preserves recognized text and timestamps. It does not prove
    sentence or scene alignment, readability, or listening acceptance.
    """
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Finite positive encoded media duration required')
    if not isinstance(words,list) or not words:
        raise ValueError('Observed ASR word timestamps required')
    previous=0.0
    for index, word in enumerate(words):
        start,end=word['start'],word['end']
        reason = None
        if type(start) not in (int,float) or type(end) not in (int,float):
            reason = 'non_numeric_time'
        elif not math.isfinite(start) or not math.isfinite(end):
            reason = 'nonfinite_time'
        elif not 0 <= start <= end <= duration:
            reason = 'outside_encoded_bounds_or_reversed_interval'
        elif start < previous-.02:
            reason = 'overlaps_previous_end_by_more_than_20ms'
        elif not isinstance(word['word'],str) or not word['word'].strip():
            reason = 'empty_or_nontext_word'
        if reason is not None:
            raise ObservedWordTimingError(index, reason, previous, duration)
        previous=end
    groups=[]; group=[]
    for word in words:
        # Zero-duration tokens may join a positive cue; never invent a duration.
        if group and group[-1]['end'] > group[0]['start'] and (
                _caption_sentence_end(group[-1]['word'])
                or word['start'] - group[-1]['end'] >= .5):
            groups.append(group); group=[]
        group.append(word)
        if len(group) == 7:
            groups.append(group); group=[]
    if group: groups.append(group)
    # Borrow one word from a capped cue when the following cue is a short tail.
    for index in range(1, len(groups)) if scene_boundaries is not None else ():
        prior, tail = groups[index - 1], groups[index]
        if len(prior) != 7 or len(tail) != 1:
            continue
        last = prior[-1]
        if (_caption_sentence_end(last['word']) or _caption_sentence_end(prior[-2]['word'])
                or not 0 <= tail[0]['start'] - last['end'] < .5
                or not 0 <= last['start'] - prior[-2]['end'] < .5):
            continue
        if any(last['start'] < boundary < tail[0]['end'] for boundary in scene_boundaries):
            continue
        original_min = min(last['end'] - prior[0]['start'], tail[0]['end'] - tail[0]['start'])
        rebalanced_min = min(prior[-2]['end'] - prior[0]['start'], tail[0]['end'] - last['start'])
        if rebalanced_min > max(0, original_min):
            tail.insert(0, prior.pop())
    lines=['WEBVTT','']
    for group in groups:
        start,end=group[0]['start'],group[-1]['end']
        if end<=start:raise ValueError('Empty observed caption duration')
        text=' '.join(' '.join(w['word'].split()) for w in group)
        lines.extend([f'{timestamp(start)} --> {timestamp(end)}',html.escape(text),''])
    return '\n'.join(lines)+'\n'


def pinned_asr_snapshot():
    """Verify the recorded immutable ASR assets before model deserialization.

    Normal Hugging Face snapshot links into this cache's blobs are supported.
    Missing assets never trigger a download, and mutable refs/main is ignored.
    """
    hub = Path(os.environ.get('HF_HUB_CACHE', str(Path(os.environ.get(
        'HF_HOME', str(Path.home() / '.cache/huggingface'))) / 'hub'))).resolve()
    snapshot = hub / 'models--Systran--faster-whisper-base.en' / 'snapshots' / ASR_REVISION
    if not snapshot.is_dir() or not snapshot.resolve().is_relative_to(hub):
        raise ValueError('Pinned ASR snapshot unavailable inside selected cache')
    if {path.name for path in snapshot.iterdir()} != set(ASR_ASSETS):
        raise ValueError('Pinned ASR snapshot must contain exactly the verified assets')
    for name, (size, expected) in ASR_ASSETS.items():
        path = snapshot / name
        if not path.is_file() or not path.resolve().is_relative_to(hub):
            raise ValueError('Pinned ASR asset outside selected cache: ' + name)
        if path.stat().st_size != size or digest(path) != expected:
            raise ValueError('Pinned ASR asset size/hash mismatch: ' + name)
    return snapshot, {'repository': ASR_REPOSITORY, 'revision': ASR_REVISION,
                      'files': {name: {'size_bytes': size, 'sha256': sha}
                                for name, (size, sha) in ASR_ASSETS.items()}}


def encoded_media_duration(video):
    """Read the playable container bound, not padded ASR decode length."""
    result = subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'json', str(video)], timeout=20)
    duration = float(json.loads(result)['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Finite positive encoded media duration required')
    return duration


def transcribe_encoded(editorial, output, voice_root, *, timeline=None):
    """Independent offline recognizer reads the encoded MP4 audio stream."""
    snapshot, model_identity = pinned_asr_snapshot()
    from faster_whisper import WhisperModel
    def no_network(*args,**kwargs):raise RuntimeError('Network disabled during ASR')
    socket.socket.connect=no_network
    helper=Path(voice_root).resolve()/'scripts/free_transcription_qa.py'
    spec=importlib.util.spec_from_file_location('cyzor_transcription_helpers',helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    video=output/'video.mp4'; candidate_hash=digest(video)
    media_duration=encoded_media_duration(video)
    timeline_sha = None
    boundaries = None
    if timeline is not None:
        timeline = Path(timeline)
        raw_timeline = timeline.read_bytes()
        timeline_sha = hashlib.sha256(raw_timeline).hexdigest()
        scenes = json.loads(raw_timeline)['scenes']
        starts = [scene['start'] for scene in scenes]
        if (not starts or len(starts) != len(editorial['scenes']) or starts[0] != 0
                or any(type(start) not in (int, float) or not 0 <= start < media_duration for start in starts)
                or any(a >= b for a,b in zip(starts, starts[1:]))):
            raise ValueError('Invalid measured scene starts')
        boundaries = tuple(starts[1:])
    samples,duration=module.decode_transcription_audio(video)
    model=WhisperModel(str(snapshot),device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)
    segments,info=model.transcribe(samples,language='en',beam_size=5,word_timestamps=True,
        vad_filter=True,condition_on_previous_text=True,
        suppress_tokens=module.spoken_number_suppression(model.hf_tokenizer))
    words=[]; texts=[]
    for segment in segments:
        texts.append(segment.text.strip())
        for word in segment.words or []:
            words.append({'word':word.word.strip(),'start':float(word.start),'end':float(word.end),
                          'probability':float(word.probability)})
    actual=' '.join(texts); expected=' '.join(scene['narration'] for scene in editorial['scenes'])
    comparison=compare_transcription(expected,actual,module.norm)
    if pinned_asr_snapshot()[1] != model_identity:
        raise ValueError('Pinned ASR identity changed during recognition')
    report={'schema_version':1,'status':'FAIL','engine':'faster-whisper','model':'base.en',
            'model_identity':model_identity,
            'candidate_sha256':candidate_hash,'editorial_sha256':editorial_digest(editorial),
            'expected_text':expected,'actual_transcript':actual,'words':words,'comparison':comparison,
            'duration_seconds':duration,'encoded_media_duration_seconds':media_duration,'helper_sha256':digest(helper),'publication_enabled':False,
            'production_approved':False,'full_av_review':False,
            'scope':'Encoded speech recognition and observed word timing; not semantic equivalence, factual, creative or listening approval.'}
    # Preserve the original observations even if strict timing validation fails.
    # This FAIL report does not approve or replace the preliminary caption file.
    report_path = output/'transcription.json'
    write_transcription_report(report_path, report)
    if not comparison['passed']:
        raise ValueError('Independent encoded speech comparison failed')
    try:
        # Validate every original observation before a display-only join can
        # replace two constituent timings with one outer interval.
        observed_captions(words,media_duration,scene_boundaries=boundaries)
        display_words, display_joins = caption_display_words(
            words, actual, scene_boundaries=boundaries or ())
        captions=observed_captions(display_words,media_duration,scene_boundaries=boundaries)
        if digest(video)!=candidate_hash:raise ValueError('Candidate changed during ASR')
        if timeline is not None and digest(timeline) != timeline_sha:
            raise ValueError('Scene timeline changed during ASR')
        success = dict(report, status='PASS', timeline_sha256=timeline_sha,
                       caption_typography={'mode':'recognized_contiguous_hyphen_compounds_v1',
                                           'joins':display_joins})
        # A successful receipt must keep the strict JSON contract before the
        # preliminary sidecar can be replaced. Diagnostic tags are FAIL-only.
        json.dumps(success, allow_nan=False)
    except ValueError as error:
        report['caption_validation_error'] = {
            'message': str(error),
            **getattr(error, 'diagnostic', {}),
        }
        write_transcription_report(report_path, report)
        raise
    (output/'captions.vtt').write_text(captions)
    success['caption_sha256'] = digest(output/'captions.vtt')
    write(report_path, success)


if __name__=='__main__':
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--synthesize',action='store_true');mode.add_argument('--transcribe',action='store_true')
    parser.add_argument('--editorial',required=True);parser.add_argument('--output',required=True);parser.add_argument('--voice-root',required=True)
    parser.add_argument('--timeline',type=Path)
    args=parser.parse_args()
    editorial=json.loads(Path(args.editorial).read_text())
    if args.synthesize:
        if args.timeline is not None: parser.error('--timeline requires --transcribe')
        synthesize(editorial,Path(args.output),args.voice_root)
    else:
        transcribe_encoded(editorial,Path(args.output),args.voice_root,timeline=args.timeline)
