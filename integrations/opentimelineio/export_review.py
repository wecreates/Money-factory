"""Export a source-bound Episode1 review packet as a rendered-media edit.

This is timeline interchange, not rendering, layer reconstruction or approval.
Uses native OTIO serialization directly; no external adapter/plugin hooks.
"""
import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess

import opentimelineio as otio

VERSION = '0.18.1'
UPSTREAM = '44236713c1db295a6ffc66189ae98dbdfd0cb9c4'
FPS, FRAMES = 24, 720
SCOPE = ('Trimmed rendered MP4 with continuous original mixed audio. Captions remain '
         'burned in; markers are editorial metadata. No recovered artwork, separated '
         'audio stems, new render, creative acceptance or NLE import verification.')
SHA = re.compile(r'^[0-9a-f]{64}$')


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(root, name, limit):
    path = root / name
    require(path.is_file() and not path.is_symlink(), f'regular file required: {name}')
    require(path.stat().st_size <= limit, f'file exceeds bounded size: {name}')
    return path


def json_file(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, f'duplicate JSON key: {key}')
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=unique)


def caption_markers(path):
    content = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    blocks = content.strip().split('\n\n')
    require(blocks.pop(0) == 'WEBVTT', 'WEBVTT header required')
    result = []
    previous_end = 0
    def millis(value):
        require(re.fullmatch(r'\d{2}:\d{2}:\d{2}\.\d{3}', value), 'invalid cue timestamp')
        h, m, s = value.split(':')
        require(int(m) < 60 and float(s) < 60, 'invalid timestamp units')
        return int(h)*3600000 + int(m)*60000 + int(s[:2])*1000 + int(s[3:])
    for block in blocks:
        lines = block.splitlines()
        require(len(lines) >= 3 and lines[0].isdigit(), 'numbered caption cue required')
        parts = lines[1].split(' --> ')
        require(len(parts) == 2, 'invalid cue interval')
        start, end = map(millis, parts)
        text = '\n'.join(lines[2:]).strip()
        require(previous_end <= start < end <= 30000 and text, 'invalid/overlapping caption cue')
        result.append({'text': text, 'start_ms': start, 'end_ms': end})
        previous_end = end
    require(result, 'captions empty')
    return result


def validate_packet(packet, expected_run_sha256):
    require(SHA.fullmatch(expected_run_sha256 or ''), 'explicit run.json SHA256 required')
    run_path = regular(packet, 'run.json', 2*1024*1024)
    require(digest(run_path) == expected_run_sha256, 'run.json hash mismatch')
    run = json_file(run_path)
    require(run.get('status') == 'AWAITING_REVIEW' and run.get('technical_status') == 'PASS', 'completed review packet required')
    require(run.get('source_inputs_unchanged') is True, 'unchanged source evidence required')
    for key in ('publication_enabled', 'production_approved', 'full_av_review'):
        require(run.get(key) is False, f'{key} must be false')
    hashes = run.get('artifacts_sha256', {})
    for name in ('video.mp4', 'video.mp4.json', 'captions.vtt'):
        path = regular(packet, name, 100*1024*1024 if name.endswith('.mp4') else 2*1024*1024)
        require(isinstance(hashes.get(name), str) and SHA.fullmatch(hashes[name]), f'missing artifact hash: {name}')
        require(digest(path) == hashes[name], f'artifact hash mismatch: {name}')
    require(run.get('candidate_sha256') == hashes['video.mp4'], 'candidate hash mismatch')
    require(run.get('caption_sha256') == hashes['captions.vtt'], 'caption hash mismatch')
    renderer = json_file(packet/'video.mp4.json')
    require(renderer.get('kind') == 'unpublished_picture_cut', 'unsupported render kind')
    require(renderer.get('video_sha256') == hashes['video.mp4'] and renderer.get('caption_sha256') == hashes['captions.vtt'], 'renderer binding mismatch')
    require(renderer.get('publication_enabled') is False and renderer.get('production_approved') is False, 'renderer publication/approval must be false')
    frames = renderer.get('frames')
    require(isinstance(frames, list) and len(frames) == 18, '18 authored cuts required')
    end = 0
    for frame in frames:
        require(isinstance(frame, dict) and all(type(frame.get(k)) is int for k in ('scene','start','end')), 'integer cut fields required')
        require(frame['scene'] >= 0 and frame['start'] == end and end < frame['end'] <= FRAMES, 'gapped/overlapping/out-of-range cuts')
        end = frame['end']
    require(end == FRAMES, '720 frames required')
    return run, frames, caption_markers(packet/'captions.vtt')


def verify_media(path):
    # No shell, protocols, remote URL or user-selected executable. Bounded metadata read.
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file', '-show_streams', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=30, check=True)
    streams = json.loads(result.stdout)['streams']
    video = [s for s in streams if s.get('codec_type') == 'video']
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    require(len(video) == len(audio) == 1, 'one video and one audio stream required')
    require(Fraction(video[0]['avg_frame_rate']) == FPS and Fraction(video[0]['r_frame_rate']) == FPS, '24fps required')
    require(int(video[0]['nb_frames']) == FRAMES and abs(float(video[0]['duration'])-30) < .001, '720-frame,30s video required')
    require(abs(float(audio[0]['duration'])-30) <= .05, 'continuous30s audio required')
    return {'video_codec': video[0]['codec_name'], 'audio_codec': audio[0]['codec_name'], 'fps': FPS, 'frames': FRAMES}


def time_range(start, duration, rate=FPS):
    return otio.opentime.TimeRange(otio.opentime.RationalTime(start, rate), otio.opentime.RationalTime(duration, rate))


def make_timeline(run, frames, cues, run_sha):
    timeline = otio.schema.Timeline(name='CYZOR Episode1 rendered-media review edit')
    timeline.metadata['cyzor'] = {'scope': SCOPE, 'candidate_sha256': run['candidate_sha256'],
        'caption_sha256': run['caption_sha256'], 'run_sha256': run_sha,
        'publication_enabled': False, 'production_approved': False, 'full_av_review': False,
        'caption_sidecar': 'captions.vtt', 'audio_policy': 'Use the Audio track once; do not also enable clip audio.'}
    video = otio.schema.Track(name='Rendered picture cuts (burned captions)', kind=otio.schema.TrackKind.Video)
    audio = otio.schema.Track(name='Original continuous mixed audio', kind=otio.schema.TrackKind.Audio)
    def reference():
        ref = otio.schema.ExternalReference(target_url='video.mp4', available_range=time_range(0, FRAMES))
        ref.metadata['sha256'] = run['candidate_sha256']
        return ref
    for frame in frames:
        clip = otio.schema.Clip(name=f"Scene {frame['scene']}", media_reference=reference(), source_range=time_range(frame['start'], frame['end']-frame['start']))
        clip.metadata['scene'] = frame['scene']
        video.append(clip)
    audio.append(otio.schema.Clip(name='Original mix', media_reference=reference(), source_range=time_range(0, FRAMES)))
    for cue in cues:
        video.markers.append(otio.schema.Marker(name=cue['text'], marked_range=time_range(cue['start_ms'], cue['end_ms']-cue['start_ms'], 1000), color=otio.schema.MarkerColor.CYAN))
    timeline.tracks.extend([video, audio])
    return timeline


def verify_roundtrip(timeline, frames, cues, candidate):
    require(len(timeline.tracks) == 2, 'track count mismatch')
    video, audio = timeline.tracks
    require(video.kind == 'Video' and audio.kind == 'Audio' and len(video) == 18 and len(audio) == 1, 'track structure mismatch')
    require(timeline.duration() == otio.opentime.RationalTime(FRAMES, FPS), 'timeline duration mismatch')
    for clip, frame in zip(video, frames):
        require(clip.source_range == time_range(frame['start'],frame['end']-frame['start']) and clip.metadata['scene'] == frame['scene'], 'cut roundtrip mismatch')
    require(audio[0].source_range == time_range(0,FRAMES), 'audio roundtrip mismatch')
    for clip in list(video)+list(audio):
        require(clip.media_reference.target_url == 'video.mp4' and clip.media_reference.metadata['sha256'] == candidate, 'relative media binding mismatch')
    require(len(video.markers) == len(cues), 'caption count mismatch')
    for marker, cue in zip(video.markers, cues):
        require(marker.name == cue['text'] and marker.marked_range == time_range(cue['start_ms'],cue['end_ms']-cue['start_ms'],1000), 'caption roundtrip mismatch')


def export(packet, output, expected_run_sha256):
    require(importlib.metadata.version('opentimelineio') == VERSION, 'pinned OTIO runtime required')
    packet = Path(packet).resolve(strict=True)
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'output already exists')
    run, frames, cues = validate_packet(packet, expected_run_sha256)
    media = verify_media(packet/'video.mp4')
    timeline = make_timeline(run,frames,cues,expected_run_sha256)
    encoded = otio.core.serialize_json_to_string(timeline)
    verify_roundtrip(otio.core.deserialize_json_from_string(encoded),frames,cues,run['candidate_sha256'])
    output.mkdir()  # Collision-safe; never overwrite, including races.
    try:
        for name in ('video.mp4','captions.vtt','run.json','video.mp4.json'):
            shutil.copyfile(packet/name,output/name)
        validate_packet(output, expected_run_sha256)  # Check copied bytes, including source mutation during copy.
        (output/'timeline.otio').write_text(encoded)
        verify_roundtrip(otio.core.deserialize_json_from_string((output/'timeline.otio').read_text()),frames,cues,run['candidate_sha256'])
        receipt = {'schema_version':1, 'status':'INTERCHANGE_VERIFIED', 'verified_at':datetime.now(timezone.utc).isoformat(),
            'scope':SCOPE, 'opentimelineio_version':VERSION, 'upstream_revision':UPSTREAM,
            'input_run_sha256':expected_run_sha256, 'candidate_sha256':run['candidate_sha256'],
            'cuts':len(frames), 'caption_markers':len(cues), 'media':media,
            'roundtrip_verified':True, 'nle_import_verified':False, 'production_approved':False,
            'publication_enabled':False, 'paid_generation_enabled':False,
            'files_sha256':{p.name:digest(p) for p in sorted(output.iterdir())}}
        (output/'export-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        return receipt
    except BaseException:
        # Only this call's freshly created directory; source packet untouched.
        shutil.rmtree(output)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-sha256',required=True)
    args=parser.parse_args()
    print(json.dumps(export(args.review_dir,args.output,args.run_sha256),indent=2))


if __name__ == '__main__':
    main()
