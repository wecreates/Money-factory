"""Export a completed picture cycle as a portable native OpenTimelineIO review.

Use authored cuts and observed MP4 timestamps. The source media stays unchanged.
"""
import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from zipfile import BadZipFile

import opentimelineio as otio

from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.cycle_short import _run, _seconds
from integrations.content_control.review_package import (
    SHA, check_deadline, copy_file, digest, no_symlinks, regular_files, require,
)
from integrations.opentimelineio.export_review import VERSION, time_range


FPS = 24
MAX_SECONDS = 600
FLAGS = dict(publication_enabled=False, paid_generation_enabled=False,
             production_approved=False, full_av_review=False, nle_import_verified=False,
             listening_verified=False, phone_playback_verified=False)
SCOPE = ('Local rendered-media interchange. Scene cuts use the measured renderer intervals and '
         'observed video presentation timestamps. WebVTT markers preserve source timing and text. '
         'The original MP4 contains the single mixed audio stream. NLE import, playback and '
         'audiovisual review require separate verification.')
SOURCE_FILES = {'video.mp4': 'delivery/video.mp4', 'captions.vtt': 'delivery/captions.vtt',
                'cycle.json': 'cycle.json', 'render.json': 'delivery/render.json',
                'package.json': 'delivery/package.json'}


def stream_clock(stream):
    time_base = Fraction(stream.get('time_base', '0'))
    start = stream.get('start_pts')
    duration = stream.get('duration_ts')
    require(time_base.numerator == 1 and time_base.denominator <= 10**9,
            'Unsupported media time base')
    require(type(start) is int and type(duration) is int and 0 <= start and 0 < duration
            and start + duration <= (MAX_SECONDS + 1) * time_base.denominator,
            'Invalid media stream timestamp range')
    return {'rate': time_base.denominator, 'start_ticks': start, 'end_ticks': start + duration}


def frame_edges(report, frame_count, clock):
    """Keep each source frame start and the terminal end in native ticks."""
    frames = report.splitlines()
    require(frames and len(frames) == frame_count, 'Decoded frame count differs from stream metadata')
    edges = []
    for frame in frames:
        fields = dict(field.split('=', 1) for field in frame.strip('|').split('|'))
        start = int(fields['best_effort_timestamp'])
        duration_text = fields.get('duration')
        duration = int(fields.get('pkt_duration', '0') if duration_text in (None, 'N/A') else duration_text)
        require(clock['start_ticks'] <= start < clock['end_ticks'] and duration > 0,
                'Invalid decoded frame timing')
        if edges:
            require(edges[-1] < start, 'Decoded video presentation timestamps must increase')
        edges.append(start)
    require(edges[0] == clock['start_ticks'] and edges[-1] + duration == clock['end_ticks'],
            'Decoded video endpoints differ from stream timing')
    return [*edges, clock['end_ticks']]


def probe_media(path, deadline):
    probe = ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file', '-f', 'mov', '-threads', '2']
    fields = 'codec_type,codec_name,time_base,start_pts,duration_ts,nb_frames,r_frame_rate,width,height'
    data = json.loads(_run([*probe, '-show_entries', 'stream=' + fields, '-of', 'json', str(path)], deadline))
    streams = {stream['codec_type']: stream for stream in data['streams']}
    require(len(data['streams']) == 2 and set(streams) == {'video', 'audio'},
            'Exactly one video stream and one original audio stream required')
    video, audio = streams['video'], streams['audio']
    require(video['codec_name'] == 'h264' and audio['codec_name'] == 'aac'
            and 0 < video['width'] * video['height'] <= 1920 * 1080,
            'Unsupported cycle media profile')
    count = int(video.get('nb_frames', '0'))
    require(Fraction(video.get('r_frame_rate', '0')) == FPS and 1 <= count <= FPS * MAX_SECONDS,
            'Bounded nominal 24 fps video required')
    clocks = {'video': stream_clock(video), 'audio': stream_clock(audio)}
    video_duration = Fraction(clocks['video']['end_ticks'] - clocks['video']['start_ticks'], clocks['video']['rate'])
    require(abs(video_duration - Fraction(count, FPS)) <= Fraction(1, 4),
            'Observed video duration differs from the nominal renderer frame grid')
    raw = _run([*probe, '-select_streams', 'v:0', '-show_entries',
                'frame=best_effort_timestamp,duration,pkt_duration', '-of', 'compact=p=0:nk=0',
                str(path)], deadline).decode('ascii')
    return clocks, frame_edges(raw, count, clocks['video'])


def scene_cuts(render, editorial, edges):
    scenes, authored = render.get('scenes'), editorial['scenes']
    require(isinstance(scenes, list) and 1 <= len(scenes) <= 30 and len(scenes) == len(authored),
            'Measured and authored scene counts must match')
    cuts, cursor = [], 0
    seen = set()
    for scene, source in zip(scenes, authored):
        require(isinstance(scene, dict), 'Measured scene object required')
        scene_id = scene.get('scene_id')
        require(isinstance(scene_id, str) and scene_id == source['id'] and scene_id not in seen,
                'Measured scene identity/order mismatch')
        seen.add(scene_id)
        bounds = [scene.get('start'), scene.get('end')]
        require(all(type(value) in (int, float) and 0 <= value <= MAX_SECONDS + .001 for value in bounds),
                'Invalid measured scene boundaries')
        nominal = [value * FPS for value in bounds]
        start, end = map(round, nominal)
        require(all(abs(value - round(value)) <= 1e-7 for value in nominal),
                'Measured scene boundaries must align to nominal renderer frames')
        require(start == cursor and start < end < len(edges), 'Incomplete or overlapping scene cuts')
        cuts.append({'scene_id': scene_id, 'start_frame': start, 'end_frame': end,
                     'start_ticks': edges[start], 'end_ticks': edges[end]})
        cursor = end
    require(cursor == len(edges) - 1, 'Measured scene cuts do not cover all decoded video frames')
    return cuts


def caption_markers(text, audio):
    header, *blocks = re.split(r'\n[^\S\n]*\n', text.rstrip('\n'))
    require(header == 'WEBVTT' and blocks, 'Plain cycle WebVTT cues required')
    cues, previous = [], 0
    audio_start, audio_end = (Fraction(audio[key], audio['rate']) for key in ('start_ticks', 'end_ticks'))
    for block in blocks:
        lines = block.splitlines()
        if lines and re.fullmatch(r'\d+', lines[0]):
            lines = lines[1:]
        require(len(lines) >= 2 and all(line.strip() and '-->' not in line for line in lines[1:]),
                'Invalid caption marker text')
        bounds = lines[0].split(' --> ')
        require(len(bounds) == 2, 'Unsupported caption cue format')
        start, end = map(_seconds, bounds)
        require(previous <= start < end and audio_start <= Fraction(start, 1000)
                and Fraction(end, 1000) <= audio_end, 'Unordered or out-of-range caption cues')
        cues.append({'text': '\n'.join(lines[1:]), 'start_ms': start, 'end_ms': end})
        previous = end
    return cues


def make_timeline(title, provenance, clocks, cuts, cues):
    timeline = otio.schema.Timeline(name=title + ' — authored rendered-media review')
    timeline.metadata['cyzor'] = provenance
    video = otio.schema.Track(name='Authored picture cuts', kind=otio.schema.TrackKind.Video)
    audio = otio.schema.Track(name='Original mixed audio', kind=otio.schema.TrackKind.Audio)
    for track, clock, stream in ((video, clocks['video'], 'v:0'), (audio, clocks['audio'], 'a:0')):
        start, end, rate = clock['start_ticks'], clock['end_ticks'], clock['rate']
        if start:
            track.append(otio.schema.Gap(source_range=time_range(0, start, rate)))
        spans = cuts if track is video else [{'start_ticks': start, 'end_ticks': end}]
        for span in spans:
            reference = otio.schema.ExternalReference(target_url='video.mp4',
                available_range=time_range(start, end - start, rate))
            reference.metadata['cyzor'] = {'candidate_sha256': provenance['candidate_sha256'],
                                            'intended_stream': stream}
            clip = otio.schema.Clip(name=span.get('scene_id', 'Original mix'), media_reference=reference,
                source_range=time_range(span['start_ticks'], span['end_ticks'] - span['start_ticks'], rate))
            if track is video:
                clip.metadata['cyzor'] = span
            track.append(clip)
    for cue in cues:
        video.markers.append(otio.schema.Marker(name=cue['text'], marked_range=time_range(
            cue['start_ms'], cue['end_ms'] - cue['start_ms'], 1000)))
    timeline.tracks.extend([video, audio])
    return timeline


def export_cycle(cycle_dir, output, *, candidate_sha256, package_sha256, timeout=180):
    require(otio.__version__ == VERSION, 'Pinned OpenTimelineIO runtime required')
    require(type(timeout) is int and 10 <= timeout <= 600, 'Timeout must be 10..600 seconds')
    require(all(isinstance(value, str) and SHA.fullmatch(value) for value in (candidate_sha256, package_sha256)),
            'Exact candidate and package SHA-256 required')
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must stay disabled')
    root, output = Path(os.path.abspath(cycle_dir)), Path(os.path.abspath(output))
    no_symlinks(root)
    no_symlinks(output)
    require(not output.exists() and not output.is_relative_to(root) and not root.is_relative_to(output),
            'Fresh output separate from source cycle required')
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + timeout
    exporter_hash = digest(__file__, deadline)
    regular_files(root / 'delivery')
    snapshot = inspect_cycle(root)
    require(snapshot['candidate_sha256'] == candidate_sha256, 'Pinned candidate differs from cycle')
    require(snapshot['cycle']['package_sha256'] == package_sha256, 'Pinned package differs from cycle')
    hashes = snapshot['files_sha256']
    provenance = {'scope': SCOPE, 'candidate_sha256': candidate_sha256, 'package_sha256': package_sha256,
                  'cycle_sha256': hashes['cycle.json'], 'caption_sha256': hashes['delivery/captions.vtt'],
                  'render_receipt_sha256': hashes['delivery/render.json'], 'caption_sidecar': 'captions.vtt',
                  'audio_policy': 'Use the Audio track once. Picture clips reference the same multiplexed MP4.',
                  **FLAGS}
    output.mkdir()
    try:
        for target, source in SOURCE_FILES.items():
            copy_file(root / source, output / target, deadline)
            require(digest(output / target, deadline) == hashes[source], 'Copied source changed: ' + target)
        media = output / 'video.mp4'
        clocks, edges = probe_media(media, deadline)
        render = json.loads((output / 'render.json').read_text(encoding='utf-8'))
        cuts = scene_cuts(render, snapshot['editorial'], edges)
        cues = caption_markers((output / 'captions.vtt').read_text(encoding='utf-8'), clocks['audio'])
        timeline = make_timeline(snapshot['editorial']['title'], provenance, clocks, cuts, cues)
        encoded = otio.core.serialize_json_to_string(timeline)
        path = output / 'timeline.otio'
        path.write_bytes(encoded.encode('utf-8'))
        decoded = otio.core.deserialize_json_from_string(path.read_text(encoding='utf-8'))
        require(json.loads(encoded) == json.loads(otio.core.serialize_json_to_string(decoded)),
                'Native OTIO serialization changed timeline data')
        duration = max(Fraction(clock['end_ticks'], clock['rate']) for clock in clocks.values())
        require(math.isclose(decoded.duration().to_seconds(), float(duration), rel_tol=0, abs_tol=1e-8),
                'Native OTIO timeline duration differs from observed streams')
        _run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-protocol_whitelist', 'file,pipe', '-threads', '2',
              '-f', 'mov', '-i', str(media), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], deadline)
        require(inspect_cycle(root) == snapshot, 'Source cycle changed during export')
        files = {path.name: digest(path, deadline) for path in sorted(output.iterdir())}
        require(all(files[target] == hashes[source] for target, source in SOURCE_FILES.items()),
                'Copied source changed during export')
        require(files['timeline.otio'] == hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
                'Timeline changed during export')
        require(digest(__file__, deadline) == exporter_hash, 'Exporter changed during export')
        check_deadline(deadline)
        receipt = {'schema_version': 1, 'status': 'INTERCHANGE_VERIFIED', **provenance, 'cuts': cuts,
                   'caption_markers': len(cues), 'video_frames': len(edges) - 1, 'nominal_fps': FPS,
                   'streams': clocks, 'files_sha256': files, 'opentimelineio_version': otio.__version__,
                   'exporter_sha256': exporter_hash,
                   'roundtrip_verified': True, 'decoded_av': 'PASS', 'original_source_unchanged': True,
                   'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat()}
        (output / 'export-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n',
                                                    encoding='utf-8')
    except BaseException:
        shutil.rmtree(output)
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--package-sha256', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    try:
        receipt = export_cycle(args.cycle_dir, args.output, candidate_sha256=args.candidate_sha256,
                               package_sha256=args.package_sha256, timeout=args.timeout)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ArithmeticError, BadZipFile, EOFError) as error:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(error), **FLAGS}))
        return 2
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
