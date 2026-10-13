#!/usr/bin/env python3
"""Private worker entry point for the pinned tools. No publishing or paid APIs.

python integrations/run.py JOB.json --runtime /path/to/isolated/runtimes
Jobs have tool, operation, input, output and operation-specific fields.
Outputs must be new files. Invoke from an authenticated worker, not a public shell API.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / 'integrations/repositories.json').read_text())
TOOLS = {entry['id']: entry for entry in REGISTRY['repositories']}


def environment(runtime):
    # Provider credentials are deliberately not inherited by these free operations.
    keep = ('PATH', 'HOME', 'TMPDIR', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(PUBLICATION_ENABLED='false', FFMPEG_ENCODER='x264',
               CLAUDE_SEO_DATA_DIR=str(runtime / 'seo'),
               YOLO_CONFIG_DIR=str(runtime / 'yolo'))
    return env


def execute(command, cwd, runtime, timeout=600, stdin=None):
    result = subprocess.run([str(x) for x in command], cwd=cwd,
                            env=environment(runtime), input=stdin,
                            text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Worker exited {result.returncode}: '
                           + (result.stderr or result.stdout)[-3000:])
    return result.stdout


def source(tool):
    entry = TOOLS[tool]
    path = ROOT / entry['path']
    if not (path / '.git').exists():
        raise ValueError(f'{tool}: source not initialized')
    actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != entry['revision']:
        raise ValueError(f'{tool}: source revision does not match registry')
    dirty = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain',
                                     '--untracked-files=no'], text=True)
    if dirty:
        raise ValueError(f'{tool}: tracked upstream source has local changes: {dirty.strip()}')
    return path


def file_input(job):
    path = Path(job['input']).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Input must be a file')
    return path


def bounds(job):
    start, end = float(job['start']), float(job['end'])
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
        raise ValueError('Require finite timestamps: 0 <= start < end')
    return start, end


def website_request(data):
    from urllib.parse import urlsplit
    url=data.get('url','')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('cyzorcreations.com','www.cyzorcreations.com') or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ValueError('Rendered website jobs require the public CYZOR HTTPS site without credentials or query parameters')
    viewport=data.get('viewport','mobile')
    if viewport not in ('mobile','desktop'):
        raise ValueError('Use mobile or desktop viewport')
    return url,viewport


def media_probe(output, runtime):
    data = json.loads(execute(['ffprobe', '-v', 'error', '-show_streams',
                              '-show_format', '-of', 'json', output], ROOT, runtime))
    if not any(s['codec_type'] == 'video' for s in data['streams']):
        raise ValueError('Output contains no video stream')
    if float(data['format'].get('duration', 0)) <= 0:
        raise ValueError('Output has no positive duration')
    execute(['ffmpeg', '-v', 'error', '-i', output, '-f', 'null', '-'], ROOT, runtime)
    return {'duration': float(data['format']['duration']),
            'streams': [{k: s[k] for k in ('codec_type', 'codec_name', 'width', 'height') if k in s}
                        for s in data['streams']]}


def run(job, runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    # Serialize media/ML operations on small workers to avoid memory exhaustion.
    with (runtime / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run(job, runtime)


def _run(job, runtime):
    if job.get('publication_enabled') or job.get('paid_generation_enabled'):
        raise ValueError('This worker does not support publication or paid generation')
    tool, operation = job['tool'], job['operation']
    upstream = source(tool)
    output = Path(job['output']).resolve()
    receipt_path = Path(str(output) + '.receipt.json')
    if output.exists() or receipt_path.exists():
        raise ValueError('Output or receipt already exists; use a new job output path')
    output.parent.mkdir(parents=True, exist_ok=True)
    is_media = False
    if (tool, operation) == ('youtube-clipper-skill', 'clip'):
        start, end = bounds(job)
        execute([runtime / 'clipper/bin/python', upstream / 'scripts/clip_video.py',
                 file_input(job), start, end, output], upstream, runtime)
        is_media = True
    elif (tool, operation) == ('youtube-clipper-skill', 'captions'):
        subtitle = Path(job['subtitles']).resolve(strict=True)
        execute([runtime / 'clipper/bin/python', upstream / 'scripts/burn_subtitles.py',
                 file_input(job), subtitle, output], upstream, runtime)
        is_media = True
    elif (tool, operation) == ('openshorts', 'vertical'):
        execute([runtime / 'openshorts/bin/python', upstream / 'main.py',
                 '--input', file_input(job), '--output', output,
                 '--skip-analysis', '--format', 'vertical'], upstream, runtime, timeout=1800)
        is_media = True
    elif (tool, operation) == ('openshorts', 'transcript-windows'):
        # Reuse the upstream sentence-boundary algorithm, without a paid LLM.
        code = ('import json,sys; from clip_selection import build_transcript_windows; '
                'd=json.load(sys.stdin); print(json.dumps(build_transcript_windows('
                'd["transcript"],d["duration"])))')
        result = execute([sys.executable, '-c', code], upstream, runtime,
                         stdin=file_input(job).read_text())
        output.write_text(json.dumps(json.loads(result), indent=2) + '\n')
    elif (tool, operation) == ('claude-seo', 'parse-html'):
        result = execute(['bash', upstream / 'scripts/claude-seo', 'run',
                          'parse_html.py', file_input(job), '--json'], upstream, runtime)
        output.write_text(json.dumps(json.loads(result), indent=2) + '\n')
    elif (tool, operation) == ('claude-seo', 'render-page'):
        url,viewport=website_request(json.loads(file_input(job).read_text()))
        result=execute(['bash',upstream/'scripts/claude-seo','run','render_page.py',url,
                        '--mode','always','--viewport',viewport,'--json','--max-text','50000'],upstream,runtime)
        rendered=json.loads(result)
        if rendered.get('error') or rendered.get('render_engine')!='playwright-chromium' or rendered.get('mode_used')!='rendered' or not 200<=int(rendered.get('status_code') or 0)<300 or not rendered.get('content'):
            raise ValueError('Live Chromium rendering did not complete successfully')
        output.write_text(json.dumps(rendered,indent=2)+'\n')
    elif (tool, operation) == ('youtube-automation-agent', 'audit'):
        code = ('const fs=require("fs");const {auditContent}=require('
                '"./utils/discoverability-adapters/darkzseo.js");'
                'process.stdout.write(JSON.stringify(auditContent(JSON.parse('
                'fs.readFileSync(0,"utf8")))));')
        result = execute(['node', '-e', code], upstream, runtime,
                         stdin=file_input(job).read_text())
        output.write_text(json.dumps(json.loads(result), indent=2) + '\n')
    elif (tool, operation) == ('ruflo', 'remember-project'):
        # Native SQLite is required: a successful fallback write is not proof of durability.
        cli = runtime / 'ruflo/node_modules/.bin/ruflo'
        database = runtime / 'cyzor-memory.db'
        execute([cli, 'memory', 'store', '--key', 'repository-integrations',
                 '--value', (ROOT / 'PROJECT_MEMORY.md').read_text(), '--namespace', 'cyzor',
                 '--no-embedding', '--require-native', '--path', database], runtime, runtime)
        retrieved = execute([cli, 'memory', 'retrieve', '--key', 'repository-integrations',
                             '--namespace', 'cyzor', '--path', database], runtime, runtime)
        if 'Wan-Video/Wan2.1' not in retrieved:
            raise ValueError('Memory read-back did not return the stored repository list')
        output.write_text(retrieved)
    elif (tool, operation) == ('wan21', 'generate'):
        python = runtime / 'wan21/bin/python'
        execute([python, '-c', 'import torch; assert torch.cuda.is_available(), "CUDA GPU required"'],
                upstream, runtime)
        model = Path(job['model_directory']).resolve(strict=True)
        if not model.is_dir():
            raise ValueError('Model directory required')
        execute([python, upstream / 'generate.py', '--task', 't2v-1.3B', '--size', '832*480',
                 '--ckpt_dir', model, '--offload_model', 'True', '--t5_cpu',
                 '--prompt', str(job['prompt']), '--save_file', output], upstream, runtime, timeout=3600)
        is_media = True
    elif (tool, operation) == ('toonflow-app', 'import-brief'):
        # Use the upstream workspace API; never mutate its internal project database.
        from urllib.request import Request, urlopen
        from urllib.parse import urlencode, urlsplit
        base = job.get('service_url', 'http://127.0.0.1:3000').rstrip('/')
        url = urlsplit(base)
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.query or url.fragment or url.path:
            raise ValueError('Toonflow imports require the private loopback service')
        params = urlencode({'directory': job['workspace_directory'],
                            'path': 'cyzor-content-brief.json', 'exclusive': 'true'})
        brief = json.loads(file_input(job).read_text())
        brief['publication_enabled'] = False
        request = Request(base + '/api/workspaces/files/write?' + params,
                          data=json.dumps(brief).encode(), method='PUT',
                          headers={'Content-Type': 'application/octet-stream'})
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if result.get('code') not in (0, 200) and result.get('success') is not True:
            raise RuntimeError('Toonflow did not acknowledge workspace import')
        output.write_text(json.dumps(result, indent=2) + '\n')
    else:
        raise ValueError(f'Unsupported operation: {tool}/{operation}')
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError('Worker returned without a nonempty output file')
    media = media_probe(output, runtime) if is_media else None
    receipt = {'schema_version': 1, 'tool': tool, 'operation': operation,
               'revision': TOOLS[tool]['revision'], 'status': 'PASS',
               'verified_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
               'media': media, 'publication_enabled': False,
               'scope': 'This operation only; not complete product or hosted readiness'}
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(json.loads(args.job.read_text()), args.runtime.resolve()), indent=2))
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error), 'publication_enabled': False}), file=sys.stderr)
        sys.exit(1)
