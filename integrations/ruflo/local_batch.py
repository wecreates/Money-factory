"""Bounded, isolated local-model execution through pinned Ruflo (never a shell agent)."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


def validate(batch):
    if not isinstance(batch, dict) or batch.get('publication_enabled') is not False:
        raise ValueError('Publication must explicitly remain disabled')
    endpoint = urlsplit(batch.get('endpoint', ''))
    if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ('', '/')
            or not endpoint.port):
        raise ValueError('Use explicit loopback HTTP endpoint and port; tunnel VPN privately')
    for key, low, high in [('workers', 1, 4), ('max_tokens', 1, 1024), ('timeout_seconds', 1, 180), ('worker_memory_mb', 128, 32768), ('shared_model_memory_mb', 0, 262144), ('render_memory_mb', 0, 262144), ('render_cpu', 0, 256)]:
        value = batch.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError('Invalid bounded ' + key)
    model = batch.get('model')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,128}', model) or model.lower() in ('sonnet', 'haiku', 'opus', 'inherit') or 'cloud' in model.lower():
        raise ValueError('An explicit installed local model ID is required')
    tasks = batch.get('tasks')
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 16:
        raise ValueError('One to sixteen tasks required')
    ids = set()
    for task in tasks:
        if (not isinstance(task, dict) or not isinstance(task.get('id'), str)
                or not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}', task['id']) or task['id'] in ids
                or not isinstance(task.get('prompt'), str) or not 1 <= len(task['prompt']) <= 8000):
            raise ValueError('Invalid or duplicate task')
        ids.add(task['id'])
    return batch


def child_environment(home):
    # No provider keys, proxies, user config, NODE_OPTIONS or inherited loaders.
    return {'PATH': os.defpath, 'HOME': str(home), 'USERPROFILE': str(home),
            'XDG_CONFIG_HOME': str(home / 'config'), 'XDG_CACHE_HOME': str(home / 'cache'),
            'CLAUDE_FLOW_CWD': str(home / 'work'), 'CLAUDE_FLOW_NO_COW_MEMORY': '1',
            'CLAUDE_FLOW_RUN_TRANSCRIPTS': '0', 'PUBLICATION_ENABLED': 'false'}


def execute_task(task, batch, runtime, node, lease_fd=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from owned_process import owned_process
    with tempfile.TemporaryDirectory(prefix='cyzor-ruflo-') as tmp:
        home = Path(tmp); work = home / 'work'; work.mkdir()
        payload = {**task, **{k: batch[k] for k in ('endpoint', 'model', 'max_tokens', 'timeout_seconds')}, 'runtime': str(runtime)}
        proc = reader = None
        try:
            with owned_process([node, str(Path(__file__).with_name('execute.mjs'))],
                    timeout=batch['timeout_seconds'] + 20, lease_fd=lease_fd,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    cwd=work, env=child_environment(home)) as proc:
                output = bytearray()
                oversized = threading.Event()
                def drain():
                    while True:
                        chunk = proc.stdout.read(65536)
                        if not chunk:
                            break
                        if len(output) + len(chunk) > 2_000_000:
                            oversized.set()
                            proc.terminate()  # Guardian cleans its owned group.
                            break
                        output.extend(chunk)
                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                proc.stdin.write(json.dumps(payload).encode())
                proc.stdin.close()
                proc.wait(timeout=batch['timeout_seconds'] + 20)
                reader.join(timeout=5)
                if oversized.is_set() or reader.is_alive():
                    raise ValueError('Oversized runtime output')
                marker = '\nCYZOR_RESULT='
                result = json.loads(output.decode().rsplit(marker, 1)[1])
                if proc.returncode or result.get('status') != 'PASS':
                    raise ValueError('Local Ruflo inference failed')
                result['output_sha256'] = hashlib.sha256(result['output'].encode()).hexdigest()
                return result
        except (subprocess.TimeoutExpired, OSError, ValueError, IndexError):
            return {'id': task['id'], 'status': 'FAIL', 'reason': 'Local execution failed or exceeded its deadline', 'publication_enabled': False}
        finally:
            if reader is not None:
                reader.join(timeout=5)
            if proc is not None:
                if proc.stdin is not None:
                    proc.stdin.close()
                if proc.stdout is not None:
                    proc.stdout.close()


def run_batch(batch, runtime, node=None):
    validate(batch)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from agent_capacity import shared_admission_lock, AdmissionBusy
        from owned_process import interruptible_processes
    except ImportError:
        return blocked('Host admission module is unavailable')
    try:
        with interruptible_processes(), shared_admission_lock() as lease_fd:
            return admitted_batch(batch, runtime, node, lease_fd)
    except (AdmissionBusy, OSError):
        return blocked('Another local batch holds admission or the host lock is unavailable')


def blocked(reason):
    return {'status': 'BLOCKED', 'reason': reason, 'executed_tasks': 0,
            'publication_enabled': False, 'production_ready': False}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Model endpoint redirects are forbidden')


def verify_local_model(batch):
    # Reject Ollama cloud/relay metadata; do not trust installed model names alone.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(batch['endpoint'].rstrip('/') + '/api/show',
        data=json.dumps({'model': batch['model']}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with opener.open(request, timeout=5) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError('Oversized model metadata')
    metadata = json.loads(raw)
    if not isinstance(metadata, dict) or not isinstance(metadata.get('model_info'), dict) or not metadata['model_info']:
        raise ValueError('Installed local model metadata is unavailable')
    for record in (metadata, metadata.get('details', {})):
        if not isinstance(record, dict) or record.get('remote_model') or record.get('remote_host'):
            raise ValueError('Remote model relay is forbidden')
    return metadata


def admitted_batch(batch, runtime, node=None, lease_fd=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from agent_capacity import collect_snapshot, recommend_capacity
    except ImportError:
        return {'status': 'BLOCKED', 'reason': 'Host capacity module is unavailable',
                'executed_tasks': 0, 'publication_enabled': False, 'production_ready': False}
    admission = recommend_capacity(collect_snapshot(), worker_memory_mb=batch['worker_memory_mb'],
        requested_workers=batch['workers'], shared_model_memory_mb=batch['shared_model_memory_mb'],
        render_memory_mb=batch['render_memory_mb'], render_cpu=batch['render_cpu'], max_workers=4)
    if admission['admitted_workers'] < batch['workers']:
        return {'status': 'BLOCKED', 'reason': 'Host capacity did not admit the requested batch',
                'capacity': admission, 'executed_tasks': 0, 'publication_enabled': False, 'production_ready': False}
    try:
        verify_local_model(batch)
    except (OSError, ValueError):
        return blocked('Installed local model verification failed; cloud relays are forbidden')
    runtime = Path(runtime).resolve(strict=True)
    node = node or shutil.which('node')
    if not node:
        raise ValueError('Node runtime is unavailable')
    with concurrent.futures.ThreadPoolExecutor(max_workers=batch['workers']) as pool:
        results = list(pool.map(lambda t: execute_task(t, batch, runtime, node, lease_fd), batch['tasks']))
    passed = sum(r['status'] == 'PASS' for r in results)
    return {'status': 'PASS' if passed == len(results) else 'FAIL', 'executed_tasks': passed,
            'requested_tasks': len(results), 'concurrency_limit': batch['workers'],
            'results': results, 'publication_enabled': False, 'production_ready': False,
            'scope': 'Local text-only Ruflo inference, no computer or shell tool access'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--batch', required=True); p.add_argument('--runtime', required=True)
    a = p.parse_args()
    report = run_batch(json.loads(Path(a.batch).read_text()), a.runtime)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 2)
