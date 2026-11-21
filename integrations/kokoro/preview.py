"""Bounded, offline q8 auditions; never changes accepted voices or media.

This is one explicitly supervised media experiment, not capacity-admitted queue
execution or a persistent service. RSS is sampled, not a kernel memory limit.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from integrations.agent_capacity import shared_admission_lock
from integrations.owned_process import owned_process, interruptible_processes

HERE = Path(__file__).resolve().parent
VOICES = ('am_adam', 'am_fenrir', 'am_michael')
RSS_LIMIT = 1536 * 1024**2
TIMEOUT = 180
WRAPPER = ('import os,resource,sys;'
           'os.sched_setaffinity(0,set(map(int,sys.argv[1].split(","))));'
           'resource.setrlimit(resource.RLIMIT_CPU,(120,125));'
           'resource.setrlimit(resource.RLIMIT_FSIZE,(67108864,67108864));'
           'os.execvpe(sys.argv[2],sys.argv[2:],os.environ)')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read_contract(path, expected_sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Require a bounded regular contract file')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Approved text contract hash mismatch')
    contract = json.loads(raw)
    if contract.get('publication_enabled') is not False or contract.get('status') != 'ACTIVE':
        raise ValueError('Active publication-disabled contract required')
    text = contract.get('narration_text')
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        raise ValueError('Require 1..1200 characters of approved narration')
    return text


def verify_assets(runtime):
    runtime = Path(runtime)
    expected = json.loads((HERE / 'model-manifest.json').read_text())
    for name, entry in expected['files'].items():
        base = runtime / 'node_modules/kokoro-js' if name.startswith('voices/') else runtime / 'model'
        path = base / name
        if not path.is_file() or path.stat().st_size != entry['size_bytes'] or digest(path) != entry['sha256']:
            raise ValueError('Pinned model or preset voice bytes differ: ' + name)
    if digest(runtime / 'package-lock.json') != digest(HERE / 'package-lock.json'):
        raise ValueError('Runtime dependency lock differs from reviewed lock')
    return expected


def process_tree_rss(pid, proc=Path('/proc')):
    """Use PPid: this executor does not expose /proc/PID/task/PID/children."""
    rows = {}
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = dict(line.split(':', 1) for line in (directory / 'status').read_text().splitlines() if ':' in line)
            state = fields.get('State', '').strip().split()[0] if fields.get('State', '').strip() else None
            rss = int(fields['VmRSS'].split()[0]) * 1024 if 'VmRSS' in fields else (0 if state == 'Z' else None)
            rows[int(directory.name)] = (int(fields['PPid']), rss)
        except (FileNotFoundError, ProcessLookupError):
            continue  # Normal exit while taking the snapshot.
    if pid not in rows:
        return None
    owned = {pid}
    while True:
        expanded = owned | {child for child, (parent, _) in rows.items() if parent in owned}
        if expanded == owned:
            if any(rows[child][1] is None for child in owned if child in rows):
                raise RuntimeError('Process memory observation unavailable')
            return sum(rows[child][1] for child in owned if child in rows)
        owned = expanded


def bounded(command, *, environment, cwd, input_bytes, log, lease_fd, cpus, timeout=TIMEOUT, rss_limit=RSS_LIMIT):
    if not sys.platform.startswith('linux') or len(cpus) != 2:
        raise ValueError('Linux/WSL and two CPU affinity slots required')
    command = [sys.executable, '-c', WRAPPER, ','.join(map(str, cpus)), *map(str, command)]
    started, peak = time.monotonic(), 0
    with Path(log).open('xb') as output:
        with owned_process(command, timeout=timeout, lease_fd=lease_fd, stdin=subprocess.PIPE,
                           stdout=output, stderr=subprocess.STDOUT, env=environment, cwd=cwd) as process:
            process.stdin.write(input_bytes)
            process.stdin.close()
            while process.poll() is None:
                rss = process_tree_rss(process.pid)
                if rss is None:
                    if process.poll() is not None:
                        break
                    raise RuntimeError('Process memory observation unavailable')
                peak = max(peak, rss)
                if peak > rss_limit or os.fstat(output.fileno()).st_size > 1024**2 or time.monotonic() - started > timeout:
                    raise RuntimeError('Preview exceeded its sampled RSS, output or wall-time bound')
                time.sleep(.025)
            returncode = process.returncode
    return {'returncode': returncode, 'elapsed_seconds': time.monotonic() - started,
            'peak_sampled_process_tree_rss_bytes': peak, 'cpu_affinity': cpus,
            'cpu_seconds_hard_limit_per_process': 125, 'wall_seconds_limit': timeout,
            'rss_stop_threshold_bytes': rss_limit,
            'rss_limit_scope': '25ms sampled PPid-tree stop threshold, not a kernel memory guarantee'}


def run_preview(runtime, contract, contract_sha256, output_dir, voice):
    if voice not in VOICES:
        raise ValueError('Only existing male preset assignments are supported')
    if not sys.platform.startswith('linux') or not hasattr(os, 'sched_getaffinity'):
        raise ValueError('Linux or WSL2 required')
    cpus = sorted(os.sched_getaffinity(0))[:2]
    if len(cpus) != 2:
        raise ValueError('Two CPU affinity slots required')
    text = read_contract(contract, contract_sha256)
    runtime = Path(runtime).absolute()
    model = verify_assets(runtime)
    node = shutil.which('node')
    if not node:
        raise ValueError('Node runtime unavailable')
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'status': 'BLOCKED', 'observed_at': datetime.now(timezone.utc).isoformat(),
              'voice': voice, 'contract_sha256': contract_sha256,
              'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'publication_enabled': False, 'paid_generation_enabled': False, 'production_approved': False,
              'production_ready': False, 'model_revision': model['model_revision'],
              'scope': 'Whole approved script spoken by one stock preset; no per-character reproduction, capacity-admitted queue, host uptime or creative approval'}
    environment = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR') if key in os.environ}
    for name in ('home', 'temporary'):
        (output / name).mkdir()
    environment.update(HOME=str(output / 'home'), TMPDIR=str(output / 'temporary'),
                       HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PUBLICATION_ENABLED='false',
                       PAID_GENERATION_ENABLED='false', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', CUDA_VISIBLE_DEVICES='')
    job = dict(runtime=str(runtime), output=str(output / 'preview.wav'), text=text, voice=voice,
               publication_enabled=False, paid_generation_enabled=False)
    try:
        with interruptible_processes(), shared_admission_lock() as lease:
            report['resources'] = bounded([node, '--max-old-space-size=256', HERE / 'generate.mjs'],
                environment=environment, cwd=runtime, input_bytes=json.dumps(job).encode(),
                log=output / 'execution.log', lease_fd=lease, cpus=cpus)
        if report['resources']['returncode'] != 0:
            raise RuntimeError('Offline q8 generation failed; inspect execution.log')
        generated = json.loads((output / 'preview.wav.json').read_text())
        if (generated.get('audio_sha256') != digest(output / 'preview.wav')
                or generated.get('text_sha256') != report['text_sha256']
                or generated.get('voice') != voice or generated.get('model_revision') != model['model_revision']
                or generated.get('production_approved') is not False or generated.get('publication_enabled') is not False):
            raise ValueError('Generated audition is not bound to this request')
        report.update(status='GENERATED_PENDING_REVIEW', audio_sha256=generated['audio_sha256'],
                      duration_seconds=generated['duration_seconds'], process_max_rss_bytes=generated['process_max_rss_bytes'])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report['reason'] = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
    finally:
        (output / 'preview-receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--contract', required=True)
    parser.add_argument('--contract-sha256', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--voice', choices=VOICES, required=True)
    args = parser.parse_args()
    result = run_preview(args.runtime, args.contract, args.contract_sha256, args.output_dir, args.voice)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'GENERATED_PENDING_REVIEW' else 2


if __name__ == '__main__':
    raise SystemExit(main())
