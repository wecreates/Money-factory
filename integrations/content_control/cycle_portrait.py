"""Prepare a native portrait brief from whole authored scenes of a landscape cycle."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from integrations.content_control.cycle_editorial import FALSE_FLAGS, compile_editorial
from integrations.content_control.cycle_package import declared_layout, inspect_media
from integrations.content_control.cycle_review import _regular, inspect_cycle
from integrations.content_control.cycle_scene_review import scene_plan
from integrations.content_control.review_package import no_symlinks, require


def prepare_portrait(cycle_dir, output, *, scene_ids, title=None):
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must stay disabled')
    require(isinstance(scene_ids, list) and 1 <= len(scene_ids) <= 30
            and all(isinstance(value, str) for value in scene_ids), 'An ordered list of scene IDs is required')
    root, output = (Path(os.path.abspath(path)) for path in (cycle_dir, output))
    no_symlinks(output)
    require(not output.exists() and not output.is_relative_to(root), 'Fresh output outside source cycle required')
    snapshot = inspect_cycle(root)
    editorial = snapshot['editorial']
    files = snapshot['files_sha256']
    render_raw = _regular(root / 'delivery/render.json').read_bytes()
    source_raw = _regular(root / 'brief.json').read_bytes()
    require(hashlib.sha256(render_raw).hexdigest() == files['delivery/render.json']
            and hashlib.sha256(source_raw).hexdigest() == files['brief.json'], 'Landscape inputs changed')
    render = json.loads(render_raw)
    require(declared_layout(editorial, render) == 'landscape', 'Native landscape source required')
    media = inspect_media(root / 'delivery/video.mp4', layout='landscape', decode=False)
    measured = scene_plan(render, editorial, media['duration_seconds'])
    order = [entry['scene_id'] for entry in measured]
    require(scene_ids[0] in order, 'Unknown source scene ID')
    start = order.index(scene_ids[0])
    end = start + len(scene_ids)
    require(order[start:end] == scene_ids, 'Scene IDs must be contiguous and in source order')
    selected = measured[start:end]
    require(selected[-1]['end_seconds'] - selected[0]['start_seconds'] <= 60,
            'Source scene span exceeds 60 seconds')
    source = json.loads(source_raw)
    bindings = {'candidate_sha256': snapshot['candidate_sha256'], 'cycle_sha256': files['cycle.json'],
                'brief_sha256': files['brief.json'], 'package_sha256': files['delivery/package.json'],
                'render_sha256': files['delivery/render.json'],
                'scenes': [{k: scene[k] for k in ('scene_id', 'start_seconds', 'end_seconds')}
                           for scene in selected]}
    flags = dict.fromkeys(FALSE_FLAGS, False)
    brief = {key: source[key] for key in ('schema_version', 'topic', 'sources', 'reference_observations',
                                          'thumbnail_copy') if key in source}
    brief.update(title=source['title'] if title is None else title, scenes=source['scenes'][start:end],
                 portrait_handoff=bindings, **flags)
    planned = compile_editorial(brief, validate_visual_shapes=True)['planned_duration_seconds']
    require(planned <= 60, 'Portrait planning duration exceeds 60 seconds')
    raw = (json.dumps(brief, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    require(len(raw) <= 256 * 1024, 'Portrait brief exceeds renderer input limit')
    receipt = {'schema_version': 1, 'status': 'PORTRAIT_BRIEF_READY', **flags,
               'recorded_at': datetime.now(timezone.utc).isoformat(), 'parent': bindings,
               'brief_sha256': hashlib.sha256(raw).hexdigest(), 'planned_duration_seconds': planned,
               'scope': 'Explicit whole-scene selection. A new portrait render regenerates audio and captions. '
                        'Parent timing, review and approval do not transfer.'}
    require(inspect_cycle(root) == snapshot, 'Landscape source changed during handoff')
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / 'brief.json').write_bytes(raw)
        (output / 'portrait-handoff.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--scene', dest='scenes', action='append', required=True)
    parser.add_argument('--title')
    args = parser.parse_args()
    print(json.dumps(prepare_portrait(args.cycle_dir, args.output, scene_ids=args.scenes, title=args.title), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
