"""Frame samples for every authored scene, bound to an existing unpublished cycle.

Measured renderer intervals drive sampling, not planned storyboard durations or
heuristic shot detection. Still frames cannot establish audiovisual acceptance.
"""
import argparse
from datetime import datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

from PIL import Image, ImageDraw

from integrations.content_control.cycle_package import declared_layout, inspect_media
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.cycle_short import _probe, _run
from integrations.content_control.review_package import digest, no_symlinks, require

FLAGS = {key: False for key in ('publication_enabled', 'paid_generation_enabled',
         'production_approved', 'production_ready', 'full_av_review', 'listening_verified',
         'independent_creative_verification')}
SCOPE = ('One sampled decoded frame per authored scene. Timing comes from the bound renderer receipt, '
         'not independent scene detection. Samples do not verify full motion, transitions, captions, '
         'pacing, listening, reference comparison, phone playback or creative acceptance.')


def scene_plan(render, editorial, duration):
    """Reject missing, reordered, overlapping or incomplete measured intervals."""
    scenes = render.get('scenes')
    require(isinstance(scenes, list) and 1 <= len(scenes) <= 30, '1..30 measured scenes required')
    authored = editorial.get('scenes', [])
    require(isinstance(authored, list) and len(authored) == len(scenes), 'Authored scene count mismatch')
    result, seen, prior_end = [], set(), 0.0
    for index, (scene, source) in enumerate(zip(scenes, authored), 1):
        require(isinstance(scene, dict) and isinstance(source, dict), 'Scene objects required')
        identity = scene.get('scene_id')
        require(isinstance(identity, str) and identity and len(identity) <= 200 and
                identity == source.get('id') and identity not in seen, 'Authored scene identity/order mismatch')
        seen.add(identity)
        start, end = scene.get('start'), scene.get('end')
        require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)) and
                0 <= start < end <= duration + .1, 'Invalid measured scene bounds')
        require(abs(start - prior_end) <= 1e-6, 'Measured scene timeline must be contiguous from zero')
        require(end - start >= .1, 'Scene too short for bounded midpoint sampling')
        result.append({'scene_number': index, 'scene_id': identity, 'start_seconds': start,
                       'end_seconds': end, 'requested_sample_seconds': (start + end) / 2,
                       'frame': f'scene-{index:02}.png'})
        prior_end = end
    require(abs(prior_end - duration) <= .1, 'Measured scene timeline does not cover media duration')
    return result


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def _gallery(output, scenes, editorial, layout):
    # The overview is for navigation; native frames remain available for text QA.
    cell_w, cell_h = 260, 179 if layout == 'landscape' else 470
    sheet = Image.new('RGB', (cell_w * 3, cell_h * math.ceil(len(scenes) / 3)), '#eeeeee')
    draw = ImageDraw.Draw(sheet)
    cards = []
    for index, (scene, source) in enumerate(zip(scenes, editorial['scenes'])):
        x, y = index % 3 * cell_w, index // 3 * cell_h
        with Image.open(output / scene['frame']) as image:
            image.thumbnail((240, cell_h - 44))
            sheet.paste(image.convert('RGB'), (x + (cell_w-image.width)//2, y + 34))
        draw.text((x+10, y+5), f"Scene {index+1} | requested {scene['requested_sample_seconds']:.3f}s", fill='black')
        label = f"{index+1}. {scene['scene_id']} ({scene['start_seconds']:.3f}–{scene['end_seconds']:.3f}s)"
        cards.append('<article><h2>' + escape(label) + '</h2><a href="' + scene['frame'] + '">'
                     '<img src="' + scene['frame'] + '" alt="' + escape(label, quote=True) + '"></a>'
                     '<p>Speaker: ' + escape(str(source.get('speaker', ''))) + '</p><p>' +
                     escape(str(source.get('narration', ''))) + '</p></article>')
    sheet.save(output / 'contact-sheet.jpg', quality=92)
    sheet.close()
    (output / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Authored scene samples</title><style>body{font:16px system-ui;max-width:1200px;margin:auto;padding:20px}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px}'
        'img{width:100%;height:auto}h2{font-size:18px}article{min-width:0;overflow-wrap:anywhere}</style>'
        '<h1>Authored scene samples</h1><p>' + escape(SCOPE) + '</p><p>Click an image for its native frame. '
        'Frames are the first decoded frame at or after each requested midpoint; they do not establish '
        'an independently measured scene boundary. External WebVTT captions are not burned into these images.</p>'
        '<p><a href="scene-review.json">Provenance receipt</a> · <a href="contact-sheet.jpg">Overview</a></p>'
        '<main>' + ''.join(cards) + '</main></html>')


def make_scene_review(cycle_dir, output, *, timeout=180):
    require(type(timeout) is int and 10 <= timeout <= 600, 'Timeout must be 10..600 seconds')
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must stay disabled')
    root = Path(os.path.abspath(cycle_dir)); output = Path(os.path.abspath(output))
    no_symlinks(root); no_symlinks(output)
    require(not output.exists() and not output.is_relative_to(root) and not root.is_relative_to(output),
            'Fresh output separate from source cycle required')
    deadline = time.monotonic() + timeout
    before = inspect_cycle(root)
    media = root / 'delivery/video.mp4'
    render = json.loads((root / 'delivery/render.json').read_text())
    layout = declared_layout(before['editorial'], render)
    source = inspect_media(media, deadline=deadline, layout=layout, decode=False) if layout else _probe(media, deadline)
    require(source['width'] * source['height'] <= 1920 * 1080, 'Scene sample pixel limit exceeded')
    scenes = scene_plan(render, before['editorial'], source['duration_seconds'])
    output.mkdir(parents=True)
    receipt = {'schema_version': 1, 'status': 'BLOCKED', **FLAGS, 'scope': SCOPE,
               'started_at': datetime.now(timezone.utc).isoformat(),
               'candidate_sha256': before['candidate_sha256'], 'source_files_sha256': before['files_sha256'],
               'tool_sha256': digest(__file__), 'media': source,
               'timing_source': 'delivery/render.json scenes (measured renderer timeline)',
               'sample_policy': 'First decoded frame at or after each requested measured-scene midpoint; native pixels, no caption burn-in.',
               'planned_storyboard_times_used': False, 'scenes': scenes}
    if layout:
        receipt['layout'] = layout
    try:
        for scene in scenes:
            frame = output / scene['frame']
            log = _run(['ffmpeg', '-hide_banner', '-v', 'info', '-xerror', '-nostdin', '-n',
                  '-protocol_whitelist', 'file,pipe', '-threads', '2', '-copyts',
                  '-ss', str(scene['requested_sample_seconds']), '-f', 'mov', '-i', str(media),
                  '-map', '0:v:0', '-vf', 'showinfo', '-frames:v', '1', '-fps_mode', 'passthrough',
                  '-an', '-map_metadata', '-1', '-threads', '1',
                  '-update', '1', str(frame)], deadline)
            # Preserve input timestamps and check the actual first decoded frame.
            # A seek can otherwise skip a short scene in low-frame-rate media.
            match = re.search(rb'\bn:\s*0\s+pts:\s*-?\d+\s+pts_time:([-+0-9.eE]+)', log)
            require(match is not None, 'Decoded sample timestamp missing')
            pts = float(match.group(1))
            require(math.isfinite(pts) and scene['start_seconds'] <= pts < scene['end_seconds'] and
                    pts + .00001 >= scene['requested_sample_seconds'], 'Decoded sample falls outside requested scene')
            scene['decoded_frame_pts_seconds'] = pts
            require(frame.is_file() and frame.stat().st_size <= 16 * 1024 * 1024, 'Missing or oversized sampled frame')
            with Image.open(frame) as image:
                require(image.size == (source['width'], source['height']), 'Sample dimensions changed')
                image.verify()
            scene['frame_sha256'] = digest(frame)
        _gallery(output, scenes, before['editorial'], layout)
        require(inspect_cycle(root) == before, 'Source cycle changed while sampling')
        require(digest(__file__) == receipt['tool_sha256'], 'Sampling implementation changed')
        require(time.monotonic() <= deadline, 'Scene review deadline exhausted')
        receipt.update(status='SCENE_SAMPLES_READY', sampled_scene_count=len(scenes),
                       artifacts_sha256={p.name: digest(p) for p in output.iterdir() if p.is_file()})
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError, KeyError, TypeError) as error:
        receipt.update(reason=str(error), partial_outputs_retained=True)
    finally:
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        _write(output / 'scene-review.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    result = make_scene_review(args.cycle_dir, args.output, timeout=args.timeout)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'SCENE_SAMPLES_READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
