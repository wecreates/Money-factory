"""Exercise the pinned REA stdio server against authorized local source."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import sys
import subprocess
import tempfile
import time

VERSION = '6.4.0'


def _manifest(target):
    if target.is_symlink() or not target.is_dir():
        raise ValueError('An unlinked source directory is required')
    result = {}
    for path in sorted(target.rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked inputs are not supported')
        if path.is_file():
            result[str(path.relative_to(target))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError('Target is empty')
    return result


def probe(runtime, target):
    target = Path(target).absolute()
    before = _manifest(target)
    package = Path(runtime).resolve() / 'node_modules/rea-agents'
    if json.loads((package / 'package.json').read_text())['version'] != VERSION:
        raise ValueError('REA version does not match reviewed pin')
    result = {'schema_version': 1, 'tool': 'REA', 'version': VERSION,
              'operation': 'mcp-stdio-source-analysis', 'status': 'BLOCKED',
              'input_sha256': before, 'publication_enabled': False,
              'paid_generation_enabled': False, 'production_ready': False,
              'scope': 'MCP transport, identity and one static source call only'}
    with tempfile.TemporaryDirectory(prefix='cyzor-rea-mcp-') as home, tempfile.TemporaryFile() as errors:
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': home,
               'PUBLICATION_ENABLED': 'false', 'PAID_GENERATION_ENABLED': 'false'}
        proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name('mcp_server.py')), '--runtime', str(Path(runtime).resolve())],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=errors, env=env)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        pending = b''
        sequence = 0

        def send(value):
            proc.stdin.write(json.dumps(value).encode() + b'\n')
            proc.stdin.flush()

        def call(method, params, timeout=90):
            nonlocal sequence, pending
            sequence += 1
            send({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params})
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    message = json.loads(line)
                    if message.get('id') == sequence:
                        if 'error' in message:
                            raise RuntimeError(json.dumps(message['error']))
                        return message['result']
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError('REA stdio closed before the response')
                pending += chunk
                if len(pending) > 16 * 1024 * 1024:
                    raise RuntimeError('REA response exceeded 16 MiB')
            raise TimeoutError(f'REA {method} timed out')

        try:
            result['initialize'] = call('initialize', {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'money-factory-verifier', 'version': '1.0.0'}})
            send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            catalog = call('tools/list', {})
            names = [tool['name'] for tool in catalog['tools']]
            result['tool_names'] = names
            result['catalog_sha256'] = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
            if len(set(names)) != len(names) or not {'binary_session', 'analyze_javascript_application'} <= set(names):
                raise RuntimeError('Required MCP tools missing or duplicated')
            result['identity'] = call('tools/call', {'name': 'binary_session', 'arguments': {}})
            result['analysis'] = call('tools/call', {'name': 'analyze_javascript_application',
                                                    'arguments': {'input_path': str(target), 'format': 'directory',
                                                                  'integrity_policy': 'fail'}})
            if result['initialize']['serverInfo']['version'] != VERSION:
                raise RuntimeError('Live MCP server version differs from pin')
            if not result['identity'].get('isError') and not result['analysis'].get('isError') and result['analysis'].get('structuredContent'):
                result['status'] = 'PASS'
        except (RuntimeError, TimeoutError, ValueError, KeyError, OSError) as exc:
            result['error'] = str(exc)
        finally:
            selector.close()
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            proc.stdout.close()
            errors.seek(0)
            result['stderr'] = errors.read(65536).decode(errors='replace')
    if _manifest(target) != before:
        raise ValueError('Target changed during MCP inspection')
    return result
