"""Isolated, text-only OpenClaw execution against an operator-owned local Ollama.

No ambient OpenClaw profile, provider credentials, tools, channels, or gateways.
This adapter is application isolation, not an OS sandbox for an untrusted CLI.
"""
import json
import http.client
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import sys
from urllib.parse import urlsplit

VERSION = '2026.11.6'
MAX_OUTPUT = 1024 * 1024


def execute(argv, cwd, env, timeout, lease_fd=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from owned_process import owned_process
    with tempfile.TemporaryFile() as out:
        with owned_process(argv, timeout=timeout, lease_fd=lease_fd, cwd=cwd,
                           env=env, stdout=out, stderr=subprocess.DEVNULL) as process:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline or os.fstat(out.fileno()).st_size > MAX_OUTPUT:
                    raise RuntimeError('OPENCLAW_TIMEOUT_OR_OUTPUT_LIMIT')
                time.sleep(.05)
            if process.returncode:
                raise RuntimeError('OPENCLAW_COMMAND_FAILED')
            out.seek(0)
            data = out.read(MAX_OUTPUT + 1)
            if len(data) > MAX_OUTPUT:
                raise RuntimeError('OPENCLAW_OUTPUT_LIMIT')
            return data.decode('utf-8')


def validate(job):
    if job.get('tool') != 'openclaw' or job.get('operation') not in ('doctor', 'run-text'):
        raise ValueError('Unsupported OpenClaw operation')
    for field in ('publication_enabled', 'paid_generation_enabled'):
        if job.get(field) is not False:
            raise ValueError('Publication and paid generation must explicitly be false')
    if set(job) - {'tool','operation','publication_enabled','paid_generation_enabled','output','model','model_url','prompt','timeout_seconds','worker_memory_mb','shared_model_memory_mb','render_memory_mb','render_cpu'}:
        raise ValueError('Unknown job options are not forwarded to OpenClaw')
    if job['operation'] == 'doctor':
        return
    if os.name == 'nt':
        raise ValueError('run-text requires POSIX process isolation; use WSL2 on Windows')
    for field in ('worker_memory_mb', 'shared_model_memory_mb', 'render_memory_mb', 'render_cpu'):
        value = job.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < (1 if field == 'worker_memory_mb' else 0):
            raise ValueError('Explicit finite nonnegative resource budgets required; worker memory must be positive')
    model = job.get('model', '')
    if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,100}', model) or 'cloud' in model.lower() or model.startswith(('http:', 'https:')):
        raise ValueError('An explicit local Ollama model name is required')
    url = job.get('model_url', '')
    if not isinstance(url, str):
        raise ValueError('Model URL must be a string')
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.port:
        raise ValueError('Model endpoint must be explicit HTTP loopback with port and no path')
    prompt = job.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 12000:
        raise ValueError('A nonempty prompt of at most 12000 bytes is required')
    timeout = job.get('timeout_seconds', 120)
    if type(timeout) is not int or not 5 <= timeout <= 300:
        raise ValueError('Timeout must be an integer from 5 to 300 seconds')


def config(job, workspace):
    model = job['model']
    return {
        'models': {'mode': 'replace', 'providers': {'ollama': {
            'baseUrl': job['model_url'], 'api': 'ollama', 'apiKey': 'ollama-local',
            'models': [{'id': model, 'name': model, 'input': ['text'],
                        'contextWindow': 16384, 'maxTokens': 1024, 'reasoning': False}]} }},
        'agents': {'defaults': {'workspace': str(workspace), 'model': {'primary': 'ollama/' + model, 'fallbacks': []},
                                'maxConcurrent': 1, 'skipBootstrap': True}},
        'tools': {'deny': ['*'], 'toolSearch': False},
        'plugins': {'allow': ['ollama'], 'slots': {'memory': 'none'}},
        'gateway': {'mode': 'local', 'bind': 'loopback'},
    }


def environment(directory):
    # Do not forward API keys, shell startup, proxies, NODE_OPTIONS, plugins, or the
    # user's profile. HOME is set for this child only, not changed in our process.
    env = {key: os.environ[key] for key in ('PATH','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP','LANG') if key in os.environ}
    env.update(HOME=str(directory), USERPROFILE=str(directory), OPENCLAW_HOME=str(directory),
               OPENCLAW_STATE_DIR=str(directory / 'state'), OPENCLAW_CONFIG_PATH=str(directory / 'config.json'),
               OPENCLAW_WORKSPACE_DIR=str(directory / 'workspace'), PUBLICATION_ENABLED='false',
               PAID_GENERATION_ENABLED='false', NO_COLOR='1')
    return env


def check_local_model(job):
    """Read bounded native Ollama metadata; no proxy, redirect or generation."""
    parsed = urlsplit(job['model_url'])
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request('POST', '/api/show', body=json.dumps({'model':job['model']}),
                           headers={'Content-Type':'application/json'})
        response = connection.getresponse()
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            raise RuntimeError('OPENCLAW_LOCAL_MODEL_METADATA_UNAVAILABLE')
        info = json.loads(raw)
        details = info.get('details', {}) if isinstance(info, dict) else {}
        if (not isinstance(details, dict) or details.get('remote_model') or details.get('remote_host')
                or not isinstance(info, dict) or not isinstance(info.get('model_info'),dict)
                or not info['model_info'] or info.get('remote_model') or info.get('remote_host')):
            raise RuntimeError('OPENCLAW_LOCAL_MODEL_NOT_VERIFIED')
    finally:
        connection.close()


def run_isolated(job, executable, lease_fd=None):
    with tempfile.TemporaryDirectory(prefix='cyzor-openclaw-') as temporary:
        directory = Path(temporary)
        (directory / 'workspace').mkdir()
        env = environment(directory)
        version = execute([executable, '--version'], directory, env, 15, lease_fd=lease_fd).strip()
        if not re.search(r'(?<![\d.])' + re.escape(VERSION) + r'(?![\d.])', version):
            raise RuntimeError('OPENCLAW_VERSION_MISMATCH')
        if job['operation'] == 'doctor':
            return {'status': 'BLOCKED', 'runtime_version': VERSION,
                    'blockers': ['MODEL_EXECUTION_NOT_TESTED'], 'model_execution_verified': False}
        (directory / 'config.json').write_text(json.dumps(config(job, directory / 'workspace')))
        prompt = directory / 'prompt.txt'
        prompt.write_text(job['prompt'])
        # --local bypasses Gateway; no --deliver, channel, recipient, or external tool.
        raw = execute([executable, 'agent', '--local', '--agent', 'main', '--model',
                       'ollama/' + job['model'], '--message-file', str(prompt), '--json',
                       '--timeout', str(job.get('timeout_seconds', 120))],
                      directory, env, job.get('timeout_seconds', 120) + 10, lease_fd=lease_fd)
        result = json.loads(raw)
        meta = result.get('meta', {}) if isinstance(result, dict) else {}
        agent = meta.get('agentMeta', {})
        trace = meta.get('executionTrace', {})
        usage = agent.get('usage', {})
        receipt = agent.get('terminalReceipt', {})
        effective = receipt.get('effective', {})
        if (meta.get('aborted') is not False or meta.get('stopReason') != 'stop'
                or agent.get('provider') != 'ollama' or agent.get('model') != job['model']
                or trace.get('winnerProvider') != 'ollama' or trace.get('winnerModel') != job['model']
                or trace.get('fallbackUsed') is not False or trace.get('runner') != 'embedded'
                or effective.get('provider') != 'ollama' or effective.get('model') != job['model']
                or receipt.get('successfulToolNames') != []
                or type(usage.get('input')) is not int or usage['input'] <= 0
                or type(usage.get('output')) is not int or usage['output'] <= 0):
            raise RuntimeError('OPENCLAW_INFERENCE_EVIDENCE_MISSING')
        # OpenClaw's local JSON result carries payloads directly. Refuse gateway
        # envelopes, errors, empty payloads and fabricated metadata-only success.
        payloads = result.get('payloads') if isinstance(result, dict) else None
        if not isinstance(payloads, list) or not payloads or any(not isinstance(p, dict) for p in payloads):
            raise RuntimeError('OPENCLAW_RESPONSE_INVALID')
        if any(p.get('isError') or p.get('mediaUrl') or p.get('mediaUrls') for p in payloads):
            raise RuntimeError('OPENCLAW_RESPONSE_NOT_TEXT')
        text = '\n'.join(p.get('text', '') for p in payloads if isinstance(p.get('text'), str)).strip()
        if not text:
            raise RuntimeError('OPENCLAW_EMPTY_RESPONSE')
        return {'status': 'PASS', 'runtime_version': VERSION, 'text': text,
                'model_execution_verified': True, 'model': job['model'],
                'usage': {'input_tokens': usage['input'], 'output_tokens': usage['output']},
                'provider': 'ollama', 'fallback_used': False}


def dispatch(job, runtime):
    validate(job)
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    output = Path(job['output'])
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists')
    executable = shutil.which('openclaw')
    report = {'schema_version': 1, 'tool': 'openclaw', 'operation': job['operation'],
              'publication_enabled': False, 'paid_generation_enabled': False,
              'tools_enabled': False, 'delivery_enabled': False, 'production_ready': False,
              'verified_agents': 0, 'scope': 'One isolated local text turn only; not host capacity or production readiness'}
    from agent_capacity import shared_admission_lock, recommend_capacity, collect_snapshot, AdmissionBusy
    try:
        with shared_admission_lock() as lease_fd:
            if executable is None:
                report.update(status='BLOCKED', blockers=['OPENCLAW_NOT_INSTALLED'], model_execution_verified=False)
            else:
                try:
                    if job['operation'] == 'run-text':
                        budget = recommend_capacity(collect_snapshot(), requested_workers=1,
                            worker_memory_mb=job['worker_memory_mb'],
                            shared_model_memory_mb=job['shared_model_memory_mb'],
                            render_memory_mb=job['render_memory_mb'], render_cpu=job['render_cpu'])
                        report['capacity'] = budget
                        if budget['admitted_workers'] < 1:
                            raise RuntimeError('OPENCLAW_CAPACITY_BLOCKED')
                        check_local_model(job)
                        report['local_model_metadata_verified'] = True
                    report.update(run_isolated(job, executable, lease_fd=lease_fd))
                    report['verified_agents'] = int(report['model_execution_verified'])
                except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
                    code = str(exc) if str(exc).startswith('OPENCLAW_') else 'OPENCLAW_EXECUTION_FAILED'
                    report.update(status='BLOCKED', blockers=[code], model_execution_verified=False)
    except AdmissionBusy:
        report.update(status='BLOCKED', blockers=['OPENCLAW_SHARED_BUDGET_BUSY'], model_execution_verified=False)
    report['verified_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    return report
