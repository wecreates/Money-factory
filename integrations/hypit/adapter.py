"""Project-owned, offline Hypit storyboard preparation and native-result intake.

No Hypit module, executable, Skill, generated program or provider is run here.
Source text is a reviewable artifact, never evaluated as an agent instruction.
"""
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct

from reel_media import digest, json_digest, read_bytes, require_disabled, result

REVISION = 'e26d9142fd8a6f78bf4f3cdb800d6205f4ecca16'
ARCHIVE_SHA256 = '9a1e40cb9597b8c8a9008735b0561faaae663f33a1ccaff19016ca13abf2bd2d'
OPERATIONS = ('status', 'prepare-project', 'validate-export')
MAX_ASSET = 16 * 1024 * 1024
MAX_VIDEO = 64 * 1024 * 1024
BLOB_TYPE = {'module': {'name': '@hypit/blob', 'version': '1'}, 'name': 'Blob'}
BLOCKERS = [
    'This offline bridge does not inspect or activate the deployment runtime; isolated cloud smoke evidence is separate',
    'Deployment runtime must be explicitly configured and verified before live rendering',
    'This operation runs no deployment compile, plan, render, media-decode or creative-quality checks',
    'Only original or user-owned local PNG inputs are accepted for this silent storyboard subset',
    'Third-party hosted/multi-tenant functionality or commercial redistribution needs separate Hypit permission',
]


def _guard(data):
    require_disabled(data)
    if any(data.get(name, False) is not False for name in ('network_enabled', 'paid_services_enabled')):
        raise ValueError('Network and paid services must remain disabled')


def _object(value, allowed, required=None):
    if not isinstance(value, dict) or set(value) - set(allowed) or (set(required or ()) - set(value)):
        raise ValueError('Unexpected or missing fields')
    return value


def _string(value, label, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label} must be nonempty bounded text without control characters')
    return value


def _id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', value):
        raise ValueError(f'{label} must be a lowercase identifier')
    return value


def _integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer between {minimum} and {maximum}')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Expected lowercase SHA-256 digest')
    return value


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON keys are not accepted')
            value[key] = item
        return value
    def finite(_):
        raise ValueError('Non-finite JSON values are not accepted')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=finite)
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def _local_file(path, sha, limit):
    _string(path, 'Local path', 4096)
    if '://' in path or '\\' in path or path.startswith('//') or '\x00' in path or '..' in Path(path).parts:
        raise ValueError('Only ordinary local paths are accepted')
    raw = read_bytes(path, limit)
    if digest(raw) != _sha(sha):
        raise ValueError('File digest does not match supplied bytes')
    return raw


def _png_dimensions(raw):
    # File identification only. Decode and aesthetic review are separate gates.
    if len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[8:16] != b'\x00\x00\x00\rIHDR':
        raise ValueError('Input must have a PNG IHDR signature')
    width, height = struct.unpack('>II', raw[16:24])
    if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 32_000_000:
        raise ValueError('PNG dimensions exceed the storyboard intake limit')
    return width, height


def prepare_project(data):
    _guard(data)
    _object(data, {'project_id', 'title', 'frame_rate', 'width', 'height', 'scenes', 'intended_use',
                   'publication_enabled', 'paid_generation_enabled'},
            {'project_id', 'title', 'scenes', 'intended_use'})
    project = _id(data['project_id'], 'project_id')
    title = _string(data['title'], 'title', 200)
    if data['intended_use'] not in ('own_organization', 'client_work'):
        raise ValueError('This bridge excludes multi-tenant services and commercial redistribution')
    fps = _integer(data.get('frame_rate', 30), 'frame_rate', 24, 60)
    if fps not in (24, 25, 30, 50, 60):
        raise ValueError('Unsupported frame rate')
    width = _integer(data.get('width', 1080), 'width', 64, 1920)
    height = _integer(data.get('height', 1920), 'height', 64, 1920)
    if width % 2 or height % 2:
        raise ValueError('Output dimensions must be even')
    scenes = data['scenes']
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 24:
        raise ValueError('Provide 1..24 storyboard scenes')
    clean, transfers, identifiers, total_frames, total_bytes = [], [], set(), 0, 0
    for scene in scenes:
        _object(scene, {'id', 'duration_frames', 'image', 'note'}, {'id', 'duration_frames', 'image'})
        ident = _id(scene['id'], 'scene id')
        if ident in identifiers:
            raise ValueError('Duplicate scene id')
        identifiers.add(ident)
        frames = _integer(scene['duration_frames'], 'duration_frames', 1, fps * 60)
        total_frames += frames
        if total_frames > fps * 180:
            raise ValueError('Storyboard exceeds three minutes')
        asset = _object(scene['image'], {'path', 'sha256', 'rights_basis', 'rights_attested'},
                        {'path', 'sha256', 'rights_basis', 'rights_attested'})
        if asset['rights_basis'] not in ('original', 'user_owned') or asset['rights_attested'] is not True:
            raise ValueError('Explicit original/user-owned asset rights attestation is required')
        raw = _local_file(asset['path'], asset['sha256'], MAX_ASSET)
        total_bytes += len(raw)
        if total_bytes > 64 * 1024 * 1024:
            raise ValueError('Storyboard assets exceed 64 MiB')
        image_width, image_height = _png_dimensions(raw)
        target = f'assets/{ident}-{asset["sha256"][:16]}.png'
        clean.append({'id': ident, 'duration_frames': frames, 'start_frame': total_frames - frames,
                      'asset': target, 'sha256': asset['sha256'], 'size_bytes': len(raw),
                      'width': image_width, 'height': image_height,
                      'rights_basis': asset['rights_basis'], 'rights_attested': True,
                      'note': _string(scene['note'], 'note', 2000) if 'note' in scene else ''})
        transfers.append({'source_path': asset['path'], 'project_path': target,
                          'sha256': asset['sha256'], 'size_bytes': len(raw)})
    # IDs and file names come only from strict identifier/hash fields. Human text is
    # held in JSON, never interpolated into markup, code, commands or a Skill prompt.
    lines = ['<?svml using="@hypit/markup@1"?>', '<svml>']
    for alias, name in [('time', 'timeline-author'), ('space', 'spatial'), ('media', 'media'),
                        ('visual', 'visual-track'), ('film', 'film'), ('html', 'html-video')]:
        lines.append(f'  <import as="{alias}" from="@hypit/{name}@1"/>')
    lines += ['  <import as="look" source="./style.svs"/>',
              f'  <time:Clock id="clock" frame-rate="{fps}"/>',
              f'  <time:Timeline id="program" clock={{clock}} end="{total_frames}f">']
    for i, scene in enumerate(clean):
        lines.append(f'    <time:Window id="scene-{i}" from="{scene["start_frame"]}f" for="{scene["duration_frames"]}f"/>')
    lines += ['  </time:Timeline>', f'  <space:Canvas id="canvas" width="{width}" height="{height}"/>']
    for i, scene in enumerate(clean):
        lines += [f'  <media:Image id="image-{i}" src="./{scene["asset"]}"/>',
                  f'  <space:Extent id="extent-{i}" width="{scene["width"]}" height="{scene["height"]}"/>']
    lines.append('  <visual:Track id="pictures" timeline={program.timeline}>')
    for i in range(len(clean)):
        lines.append(f'    <visual:Clip id="clip-{i}" image={{image-{i}}} extent={{extent-{i}}} during={{program.scene-{i}}} frame={{canvas.bounds}} z="0" fit="contain"/>')
    lines += ['  </visual:Track>',
              '  <film:Film id="main" canvas={canvas.canvas} timeline={program.timeline} appearance={look.film.main}>',
              '    <film:Track source={pictures.visual}/>', '  </film:Film>',
              '  <html:Video id="final" composition={main.composition} timeline={program.timeline}/>', '</svml>']
    files = {
        'main.svml': '\n'.join(lines) + '\n',
        'style.svs': '<?svml using="@hypit/recipe@1"?>\n<sheet version="1">\n  film.main { background: #101820; }\n</sheet>\n',
        'build.svrun': '<?svml using="@hypit/markup/run@1"?>\n<svrun version="1">\n  <author source="./main.svml"/>\n  <target output="final.video"/>\n</svrun>\n',
        'package.json': json.dumps({'name': 'cyzor-hypit-' + project, 'version': '0.0.0', 'private': True,
                                    'hypit': {'project': True}}, indent=2) + '\n',
    }
    binding = {'project_id': project, 'title': title, 'intended_use': data['intended_use'],
               'frame_rate': fps, 'width': width, 'height': height, 'total_frames': total_frames,
               'scenes': clean, 'files_sha256': {name: digest(value.encode()) for name, value in files.items()},
               'upstream_revision': REVISION, 'output_name': 'final.video'}
    return result('hypit', 'prepare-project', project=binding, request_sha256=json_digest(binding),
                  project_files=files, asset_transfers=transfers, runtime_status='DEPLOYMENT_RUNTIME_NOT_VERIFIED',
                  upstream_revision=REVISION, source_status='PINNED_STATIC_REVIEW_ONLY',
                  execution_status='NOT_COMPILED_OR_RENDERED', upstream_compile_verified=False,
                  full_decode_verified=False, narration_included=False, silent_storyboard=True, asset_source_attestation='caller_supplied',
                  blockers=BLOCKERS, cost={'provider_calls': 0, 'provider_charge_authorized': 0,
                  'future_render_cost_verified': False},
                  scope='Offline silent storyboard source package; files and transfer list only, no asset copy or runtime execution')


def validate_export(data):
    _guard(data)
    _object(data, {'preparation', 'export', 'publication_enabled', 'paid_generation_enabled'},
            {'preparation', 'export'})
    prepared = prepare_project(data['preparation'])
    exported = _object(data['export'], {'path', 'sha256', 'request_sha256', 'result_path', 'result_sha256'},
                       {'path', 'sha256', 'request_sha256', 'result_path', 'result_sha256'})
    if exported['request_sha256'] != prepared['request_sha256']:
        raise ValueError('Export request binding does not match preparation')
    raw = _local_file(exported['path'], exported['sha256'], MAX_VIDEO)
    if len(raw) < 16 or raw[4:8] != b'ftyp':
        raise ValueError('Export lacks an MP4 file-type box signature')
    report_raw = _local_file(exported['result_path'], exported['result_sha256'], 2 * 1024 * 1024)
    report = _json(report_raw)
    if report.get('format') != 'hypit.build-result@1' or report.get('outcome') != 'complete':
        raise ValueError('A completed native Hypit Build Result is required')
    finished = report.get('finishedAt')
    if type(finished) not in (int, float) or not math.isfinite(finished) or finished <= 0:
        raise ValueError('Completed result must contain a finite finishedAt')
    for key in ('source', 'run'):
        if not isinstance(report.get(key), dict):
            raise ValueError('Native result requires source and run identities')
        _string(report[key].get('id'), key + ' id', 4096)
    if not isinstance(report.get('targets'), list) or 'final.video' not in report['targets']:
        raise ValueError('Result does not target final.video')
    outputs = report.get('outputs')
    entry = outputs.get('final.video') if isinstance(outputs, dict) else None
    if not isinstance(entry, dict) or entry.get('type') != BLOB_TYPE:
        raise ValueError('Result final.video must be a Hypit Blob')
    ref = entry.get('value')
    if not isinstance(ref, dict) or ref.get('kind') != 'build-file' or 'build' in ref:
        raise ValueError('Only a direct local build-file result is accepted; resolve forwarding separately')
    if ref.get('mediaType') != 'video/mp4' or type(ref.get('size')) is not int or ref['size'] != len(raw):
        raise ValueError('Result output media type or size mismatch')
    relative = ref.get('path')
    if not isinstance(relative, str) or '\\' in relative or ':' in relative or '\x00' in relative or relative.startswith('/') or any(p in ('', '.', '..') for p in relative.split('/')):
        raise ValueError('Result output path must stay within its result directory')
    result_dir = Path(exported['result_path']).absolute().parent
    native_path = result_dir.joinpath(*PurePosixPath(relative).parts)
    native = _local_file(str(native_path), exported['sha256'], MAX_VIDEO)
    if native != raw:
        raise ValueError('Export does not match the declared native result bytes')
    return result('hypit', 'validate-export', upstream_revision=REVISION, candidate={
        'project_id': prepared['project']['project_id'], 'kind': 'video', 'media_type': 'video/mp4',
        'sha256': digest(raw), 'size_bytes': len(raw), 'request_sha256': prepared['request_sha256'],
        'native_result_sha256': digest(report_raw), 'state': 'PENDING_MEDIA_DECODE_AND_REVIEW',
        'native_result_file_binding_verified': True, 'full_decode_verified': False,
        'upstream_execution_verified': False, 'source_generation_verified': False,
        'source_attestation': 'caller_supplied', 'audible_narration_expected': False,
        'silent_audio_track_permitted': True},
        preserved_report={'path': exported['result_path'], 'sha256': digest(report_raw),
                          'modified': False, 'brand': 'Hypit', 'format': 'hypit.build-result@1'},
        required_reviews=['full_media_decode', 'duration_and_dimensions', 'visual_quality',
                          'asset_rights', 'source_to_render_match', 'creative'],
        scope='Local output identity, native result file binding and caller request binding only; reports remain unchanged')


def dispatch(job, upstream=None):
    _guard(job)
    if job.get('tool') != 'hypit':
        raise ValueError('Expected hypit tool')
    operation = job.get('operation')
    if operation == 'status':
        return result('hypit', operation, status='BLOCKED', upstream_revision=REVISION,
                      archive_sha256=ARCHIVE_SHA256, runtime_status='DEPLOYMENT_RUNTIME_NOT_VERIFIED',
                      source_status='DOWNLOADED_STATIC_REVIEW_ONLY', supported_operations=list(OPERATIONS),
                      live_execution_enabled=False, blockers=BLOCKERS,
                      scope='Offline preparation and native export intake available; no installed/runtime claim')
    if operation not in OPERATIONS:
        raise ValueError('Unsupported Hypit operation')
    data = _json(read_bytes(job.get('input'), 2 * 1024 * 1024))
    return prepare_project(data) if operation == 'prepare-project' else validate_export(data)
