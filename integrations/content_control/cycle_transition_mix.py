"""Create one unpublished, offline transition-cue mix from a verified render.

The cue is an original deterministic PCM signal placed only in the renderer's
measured post-narration tail.  This is technical sound-design evidence, not a
claim that a person listened to or approved the mix.
"""
import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave


SCHEMA_VERSION = 1
RATE = 24000
CUE_SECONDS = .16
CUE_END_MARGIN_SECONDS = .04
MIN_POST_NARRATION_TAIL_SECONDS = .24
CUE_PEAK = .03
ENCODED_PEAK_CEILING = .98
# FFmpeg 6's AAC decode exposes exactly two 1024-sample priming/padding frames
# in the hosted fixture. Keep this an exact frame ceiling, not a time-derived
# tolerance that could hide a longer content mismatch.
MAX_CODEC_TIMELINE_PADDING_FRAMES = 2048
MAX_DURATION_SECONDS = 600
MAX_SCENES = 64
VOICE_ASSIGNMENTS = {'dave': 'am_fenrir', 'points_monk': 'am_michael',
                     'narrator': 'am_adam'}
SCOPE = ('Original deterministic offline transition cues mixed only into measured '
         'post-narration tails. Exact source voices and assets are bound; direct full-mix '
         'listening is still required for sound, voice, timing, and creative acceptance.')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True,
                                     allow_nan=False) + '\n')


def safe_path(value):
    path = Path(os.path.abspath(value))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Symlink paths are not accepted')
    return path


def read_json(path, limit=2 * 1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError('Missing, symlinked, empty, or oversized JSON evidence')
    return json.loads(path.read_bytes())


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_source(render_root):
    """Bind a completed renderer, exact voices, and transition-safe intervals."""
    root = safe_path(render_root)
    if not root.is_dir():
        raise ValueError('Render root must be a directory')
    required = ('render.json', 'timeline.json', 'voice.json', 'video.mp4')
    paths = {name: root / name for name in required}
    for path in paths.values():
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise ValueError('Render evidence is missing or symlinked')
    if paths['video.mp4'].stat().st_size > 1024 * 1024 * 1024:
        raise ValueError('Source video exceeds one GiB')
    rendered = read_json(paths['render.json'])
    timeline = read_json(paths['timeline.json'])
    voice = read_json(paths['voice.json'])
    if (rendered.get('status') != 'AWAITING_REVIEW'
            or rendered.get('technical_status') != 'PASS'
            or any(rendered.get(name) is not False for name in
                   ('publication_enabled', 'paid_generation_enabled',
                    'production_approved', 'full_av_review'))):
        raise ValueError('Exact unpublished renderer contract required')
    video_sha = digest(paths['video.mp4'])
    timeline_sha = digest(paths['timeline.json'])
    voice_sha = digest(paths['voice.json'])
    if (rendered.get('candidate_sha256') != video_sha
            or rendered.get('timeline_sha256') != timeline_sha
            or rendered.get('voice_receipt_sha256') != voice_sha):
        raise ValueError('Renderer identities do not match exact source files')
    if timeline.get('publication_enabled') is not False:
        raise ValueError('Timeline must retain publication disabled')
    duration = timeline.get('duration_seconds')
    rows = timeline.get('scenes')
    clips = voice.get('clips')
    if (not _finite(duration) or not 0 < duration <= MAX_DURATION_SECONDS
            or not isinstance(rows, list) or not 2 <= len(rows) <= MAX_SCENES
            or not isinstance(clips, list) or len(clips) != len(rows)
            or voice.get('status') != 'GENERATED_PENDING_LISTENING_REVIEW'
            or voice.get('voice_assignments') != VOICE_ASSIGNMENTS
            or any(voice.get(name) is not False for name in
                   ('publication_enabled', 'paid_generation_enabled',
                    'production_approved', 'full_av_review'))):
        raise ValueError('Exact pending-listening voice and timeline contract required')
    cues = []
    voice_assets = []
    previous_end = 0.0
    for index, (row, clip) in enumerate(zip(rows, clips)):
        start, end, narration_end = (row.get('start'), row.get('end'),
                                     row.get('narration_end'))
        if (not all(_finite(value) for value in (start, end, narration_end))
                or abs(start - previous_end) > 1e-6
                or not start < narration_end < end
                or row.get('scene_id') != clip.get('scene_id')):
            raise ValueError('Timeline rows must be finite, contiguous, and voice-bound')
        speaker = clip.get('speaker')
        wav = root / f'voice-{index:02d}.wav'
        if (speaker not in VOICE_ASSIGNMENTS
                or clip.get('voice_id') != VOICE_ASSIGNMENTS[speaker]
                or clip.get('file') != wav.name
                or wav.is_symlink() or not wav.is_file()
                or clip.get('audio_sha256') != digest(wav)):
            raise ValueError('Exact preserved voice asset binding required')
        voice_assets.append({'scene_id': row['scene_id'], 'speaker': speaker,
                             'voice_id': clip['voice_id'], 'file': wav.name,
                             'sha256': digest(wav)})
        if index < len(rows) - 1:
            tail = end - narration_end
            if tail + 1e-9 < MIN_POST_NARRATION_TAIL_SECONDS:
                raise ValueError('Transition cue requires a measured post-narration tail')
            cue_end = end - CUE_END_MARGIN_SECONDS
            cue_start = cue_end - CUE_SECONDS
            if cue_start < narration_end - 1e-9:
                raise ValueError('Transition cue would overlap measured narration')
            cues.append({'from_scene_id': row['scene_id'],
                         'to_scene_id': rows[index + 1].get('scene_id'),
                         'start_seconds': cue_start, 'end_seconds': cue_end})
        previous_end = end
    if abs(previous_end - duration) > 1e-6:
        raise ValueError('Timeline duration does not match its final scene')
    return {'root': root, 'video_path': paths['video.mp4'],
            'source_candidate_sha256': video_sha,
            'render_receipt_sha256': digest(paths['render.json']),
            'timeline_sha256': timeline_sha, 'voice_receipt_sha256': voice_sha,
            'duration_seconds': duration, 'cues': cues,
            'voice_assets': voice_assets}


def cue_samples():
    """Generate an original soft rising two-part sine cue with a Hann envelope."""
    count = round(CUE_SECONDS * RATE)
    values = []
    phase = 0.0
    for index in range(count):
        progress = index / max(1, count - 1)
        frequency = 620 + 280 * progress
        phase += 2 * math.pi * frequency / RATE
        envelope = .5 - .5 * math.cos(2 * math.pi * progress)
        overtone = math.sin(phase * 1.5) * .18
        value = CUE_PEAK * envelope * (math.sin(phase) + overtone) / 1.18
        values.append(max(-1.0, min(1.0, value)))
    return values


def pcm_array(samples):
    if isinstance(samples, array) and samples.typecode == 'h':
        return samples
    return array('h', (round(max(-1.0, min(1.0, value)) * 32767)
                       for value in samples))


def pcm_bytes(samples):
    values = pcm_array(samples)
    if sys.byteorder == 'little':
        return values.tobytes()
    copy = array('h', values)
    copy.byteswap()
    return copy.tobytes()


def write_pcm(path, samples):
    integers = pcm_array(samples)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm_bytes(integers))
    return integers


def pcm_stats(samples):
    if not samples:
        raise ValueError('Decoded audio is empty')
    return {'frames': len(samples), 'duration_seconds': len(samples) / RATE,
            'rms': math.sqrt(sum(value * value for value in samples) / len(samples)) / 32767,
            'peak': max(abs(value) for value in samples) / 32767,
            'pcm_s16le_sha256': hashlib.sha256(pcm_bytes(samples)).hexdigest()}


def decode_audio(path):
    result = subprocess.run([
        'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(path),
        '-map', '0:a:0', '-ac', '1', '-ar', str(RATE), '-f', 's16le', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    if len(result.stdout) % 2:
        raise ValueError('Decoded PCM payload is incomplete')
    values = array('h')
    values.frombytes(result.stdout)
    if sys.byteorder != 'little':
        values.byteswap()
    return values


def _window_rms(samples, start, end):
    first, last = round(start * RATE), round(end * RATE)
    values = samples[first:last]
    if not values:
        raise ValueError('Cue window is outside decoded audio')
    return math.sqrt(sum(value * value for value in values) / len(values)) / 32767


def validate_decoded_lengths(source_frames, mixed_frames, duration_seconds):
    """Allow only bounded AAC priming/padding drift across FFmpeg versions."""
    if (type(source_frames) is not int or type(mixed_frames) is not int
            or source_frames <= 0 or mixed_frames <= 0
            or not _finite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('Decoded timeline lengths must be positive and finite')
    maximum_drift_frames = MAX_CODEC_TIMELINE_PADDING_FRAMES
    expected_frames = round(duration_seconds * RATE)
    if (abs(source_frames - expected_frames) > maximum_drift_frames
            or abs(mixed_frames - expected_frames) > maximum_drift_frames
            or abs(source_frames - mixed_frames) > maximum_drift_frames):
        raise ValueError('Mixed audio does not retain source timeline length')


def encoded_stream_sha256(path, selector):
    result = subprocess.run([
        'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(path),
        '-map', selector, '-c', 'copy', '-f', 'hash', '-hash', 'sha256', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    prefix = 'SHA256='
    value = result.stdout.strip()
    if not value.startswith(prefix) or len(value) != len(prefix) + 64:
        raise ValueError('Unable to bind encoded media stream')
    return value[len(prefix):]


def create_transition_mix(render_root, output):
    if any(os.environ.get(name, 'false').lower() != 'false' for name in
           ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')):
        raise ValueError('Publishing and paid generation must remain disabled')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg and FFprobe are required')
    source = validate_source(render_root)
    destination = safe_path(output)
    if destination.exists():
        raise ValueError('Mix output must not already exist')
    if destination == source['root'] or destination in source['root'].parents \
            or source['root'] in destination.parents:
        raise ValueError('Mix output and source render must be separate')
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version': SCHEMA_VERSION, 'status': 'BLOCKED',
               'technical_status': 'PENDING', 'started_at': stamp(),
               'publication_enabled': False, 'paid_generation_enabled': False,
               'production_approved': False, 'full_av_review': False,
               'production_ready': False, 'listening_verified': False,
               'scope': SCOPE,
               'tool_sha256': digest(Path(__file__).resolve()),
               'source_candidate_sha256': source['source_candidate_sha256'],
               'render_receipt_sha256': source['render_receipt_sha256'],
               'timeline_sha256': source['timeline_sha256'],
               'voice_receipt_sha256': source['voice_receipt_sha256'],
               'preserved_voice_assets': source['voice_assets']}
    write(destination / 'mix.json', receipt)
    source_before = digest(source['video_path'])
    try:
        cue = cue_samples()
        cue_path = destination / 'transition-cue.wav'
        cue_pcm = write_pcm(cue_path, cue)
        stem_count = round(source['duration_seconds'] * RATE)
        stem = array('h', [0]) * stem_count
        placements = []
        for cue_row in source['cues']:
            offset = round(cue_row['start_seconds'] * RATE)
            if offset < 0 or offset + len(cue_pcm) > len(stem):
                raise ValueError('Cue placement exceeds bounded transition stem')
            for index, value in enumerate(cue_pcm):
                stem[offset + index] += value
            placements.append(dict(cue_row, start_frame=offset,
                                   end_frame=offset + len(cue_pcm)))
        stem_path = destination / 'transition-stem.wav'
        write_pcm(stem_path, stem)
        video_path = destination / 'video.mp4'
        command = [
            'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
            '-i', str(source['video_path']), '-i', str(stem_path),
            '-filter_complex',
            '[0:a:0]aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono[voice];'
            '[1:a:0]aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono[cue];'
            '[voice][cue]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]',
            '-map', '0:v:0', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'aac',
            '-b:a', '128k', '-ar', str(RATE), '-ac', '1', '-movflags', '+faststart',
            str(video_path)]
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       check=True, timeout=180)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(video_path),
                        '-f', 'null', '-'], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=True, timeout=180)
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
            str(video_path)]))
        streams = probe.get('streams', [])
        video = next((item for item in streams if item.get('codec_type') == 'video'), None)
        audio = next((item for item in streams if item.get('codec_type') == 'audio'), None)
        encoded_duration = float(probe.get('format', {}).get('duration', 'nan'))
        if (not video or not audio or video.get('codec_name') != 'h264'
                or audio.get('codec_name') != 'aac' or audio.get('sample_rate') != str(RATE)
                or not math.isfinite(encoded_duration)
                or abs(encoded_duration - source['duration_seconds']) > .25):
            raise ValueError('Mixed output does not retain the bounded media contract')
        source_pcm = decode_audio(source['video_path'])
        mixed_pcm = decode_audio(video_path)
        validate_decoded_lengths(len(source_pcm), len(mixed_pcm),
                                 source['duration_seconds'])
        source_stats = pcm_stats(source_pcm)
        mixed_stats = pcm_stats(mixed_pcm)
        if mixed_stats['peak'] > ENCODED_PEAK_CEILING:
            raise ValueError('Mixed audio exceeds encoded peak ceiling')
        source_video_stream = encoded_stream_sha256(source['video_path'], '0:v:0')
        mixed_video_stream = encoded_stream_sha256(video_path, '0:v:0')
        if source_video_stream != mixed_video_stream:
            raise ValueError('Mixed candidate changed the encoded picture stream')
        cue_windows = []
        for placement in placements:
            source_rms = _window_rms(source_pcm, placement['start_seconds'],
                                     placement['end_seconds'])
            mixed_rms = _window_rms(mixed_pcm, placement['start_seconds'],
                                    placement['end_seconds'])
            if mixed_rms < .005 or mixed_rms <= source_rms + .002:
                raise ValueError('Encoded mix does not contain measurable cue-window energy')
            cue_windows.append(dict(placement, source_rms=source_rms,
                                    mixed_rms=mixed_rms))
        end_source = validate_source(source['root'])
        if (digest(source['video_path']) != source_before
                or any(end_source[name] != source[name] for name in
                       ('source_candidate_sha256', 'render_receipt_sha256',
                        'timeline_sha256', 'voice_receipt_sha256', 'cues',
                        'voice_assets'))):
            raise ValueError('Source candidate changed while mixing')
        receipt.update(status='AWAITING_LISTENING_REVIEW', technical_status='PASS',
                       candidate_sha256=digest(video_path),
                       duration_seconds=encoded_duration,
                       cue_asset={'file': cue_path.name, 'sha256': digest(cue_path),
                                  'generator': 'original_rising_two_part_sine_hann_v1',
                                  'sample_rate': RATE, 'channels': 1,
                                  'duration_seconds': CUE_SECONDS,
                                  'designed_peak': CUE_PEAK},
                       stem_asset={'file': stem_path.name, 'sha256': digest(stem_path),
                                   'sample_rate': RATE, 'channels': 1,
                                   'duration_seconds': len(stem) / RATE},
                       cue_placements=cue_windows,
                       encoded_picture_stream_sha256=source_video_stream,
                       encoded_peak_ceiling=ENCODED_PEAK_CEILING,
                       source_decoded_audio=source_stats,
                       mixed_decoded_audio=mixed_stats,
                       mix_algorithm='ffmpeg_amix_no_normalization_v1')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            wave.Error) as error:
        receipt.update(status='BLOCKED', technical_status='FAIL', reason=str(error))
    finally:
        receipt['finished_at'] = stamp()
        write(destination / 'mix.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--render-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    result = create_transition_mix(args.render_root, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['technical_status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
