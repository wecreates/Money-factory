"""Exercise the real registered stdio launcher on a self-contained CYZOR page."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from integrations.owned_process import owned_process, interruptible_processes
from integrations.obscura.runtime import verify_runtime

FIXTURE = '''<!doctype html><html><head><title>CYZOR browser connection</title>
<style>body{font-family:sans-serif;background:#f5f6fa;color:#112244;padding:32px}button{background:#1764d2;color:white;padding:12px}h1{font-size:32px}</style></head>
<body><h1>CYZOR browser connection</h1><label for="channel">Channel</label>
<input id="channel"><button id="preview" onclick="document.getElementById('status').textContent='Ready for review: '+document.getElementById('channel').value">Preview locally</button>
<p id="status">Awaiting input</p><p>Publishing disabled</p></body></html>'''


def run(runtime, output):
    binary = verify_runtime(Path(runtime))
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'BLOCKED', 'observed_at': datetime.now(timezone.utc).isoformat(),
               'runtime_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'publication_enabled': False, 'paid_generation_enabled': False,
               'fixture_sha256': hashlib.sha256(FIXTURE.encode()).hexdigest(), 'calls': [],
               'scope': 'Real MCP navigation, DOM interaction, snapshot and PNG capture on an owned inline fixture; no account access or third-party-site compatibility claim.'}
    command = [sys.executable, str(Path(__file__).with_name('mcp_launcher.py')),
               '--runtime', str(Path(runtime).resolve())]
    try:
        with (output/'stderr.log').open('w') as log, interruptible_processes():
            with owned_process(command, timeout=45, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=log, text=True, env={'PATH': os.environ.get('PATH', '')}) as process:
                counter = 0
                def ask(method, params):
                    nonlocal counter
                    counter += 1
                    process.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params})+'\n')
                    process.stdin.flush()
                    for _ in range(100):
                        line = process.stdout.readline(8*1024*1024)
                        if not line or not line.endswith('\n'):
                            raise RuntimeError('Missing or oversized MCP response')
                        value = json.loads(line)
                        if value.get('id') != counter:
                            continue
                        if 'error' in value or value.get('result', {}).get('isError'):
                            raise RuntimeError('MCP error: '+json.dumps(value)[:2000])
                        receipt['calls'].append({'method':method,'tool':params.get('name'),'status':'PASS'})
                        return value['result']
                    raise RuntimeError('MCP response limit exhausted')
                initialized = ask('initialize', {'protocolVersion':'2024-11-05','capabilities':{},
                    'clientInfo':{'name':'cyzor-obscura-verification','version':'1'}})
                receipt['server'] = initialized['serverInfo']
                if (initialized.get('protocolVersion')!='2024-11-05'
                    or receipt['server']!={'name':'obscura-mcp','version':'0.2.7'}):
                    raise RuntimeError('Unexpected MCP server identity')
                process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n')
                process.stdin.flush()
                tools = ask('tools/list', {})['tools']
                names = {tool['name'] for tool in tools}
                required = {'browser_navigate','browser_snapshot','browser_fill','browser_click','browser_screenshot','browser_close'}
                if not required <= names or 'web_search' in names or len(names)!=len(tools):
                    raise RuntimeError('Unexpected browser tool inventory')
                receipt['tool_count'] = len(tools)
                def call(name, args):
                    return ask('tools/call', {'name':name,'arguments':args})
                def text_content(result):
                    return '\n'.join(x['text'] for x in result.get('content',[]) if x.get('type')=='text')
                call('browser_navigate', {'url':'data:text/html,'+quote(FIXTURE)})
                before = text_content(call('browser_snapshot', {'max_chars':4000}))
                if 'CYZOR browser connection' not in before or 'Awaiting input' not in before:
                    raise RuntimeError('Initial page not observed')
                call('browser_fill', {'selector':'#channel','value':'CYZOR'})
                call('browser_click', {'selector':'#preview'})
                after = text_content(call('browser_snapshot', {'max_chars':4000}))
                if 'Ready for review: CYZOR' not in after or 'Publishing disabled' not in after:
                    raise RuntimeError('DOM interaction not observed')
                screenshot = call('browser_screenshot', {'width':720,'height':480})
                images = [x for x in screenshot.get('content',[]) if x.get('type')=='image' and x.get('mimeType')=='image/png']
                if len(images)!=1:
                    raise RuntimeError('PNG capture missing')
                png = base64.b64decode(images[0]['data'], validate=True)
                if png[:8]!=b'\x89PNG\r\n\x1a\n' or struct.unpack('>II',png[16:24])!=(720,480):
                    raise RuntimeError('Unexpected PNG dimensions')
                (output/'fixture.png').write_bytes(png)
                receipt['screenshot_sha256'] = hashlib.sha256(png).hexdigest()
                receipt['before_snapshot'] = before
                receipt['after_snapshot'] = after
                call('browser_close', {})
                receipt['status'] = 'PASS'
    except Exception as exc:
        receipt['error'] = str(exc)
    finally:
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.runtime, args.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('before_snapshot','after_snapshot')},indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 1)
