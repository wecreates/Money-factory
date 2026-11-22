"""Bounded Obscura inspection of the exact self-contained reviewed local page."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import zlib
from urllib.parse import urlsplit

from .runtime import PIN, verify_runtime, digest, no_links
try:
    from integrations.agent_capacity import shared_admission_lock
    from integrations.owned_process import owned_process, interruptible_processes
except ModuleNotFoundError:  # Existing integrations/run.py script entry point.
    from agent_capacity import shared_admission_lock
    from owned_process import owned_process, interruptible_processes

FIXTURE_SHA256 = 'ff23f3592020760b6211b88448eee81eb871f517d86390b39c1608d61f37b9f3'
EXPRESSION = '''JSON.stringify((function(){const before=document.getElementById('state').textContent;document.getElementById('activate').click();return {title:document.title,before:before,after:document.getElementById('state').textContent,javascript:document.body.getAttribute('data-engine'),text:document.body.innerText};})())'''
PUBLIC_HOSTS = {'example.com','cyzorcreations.com','www.cyzorcreations.com','content-control-render-worker.onrender.com'}
PUBLIC_EXPRESSION = "JSON.stringify({title:document.title,text:document.body.innerText.slice(0,50000),url:location.href})"
MAX_OUTPUT = 1024 * 1024

def public_url(value):
    if not isinstance(value,str) or len(value)>2048:
        raise ValueError('A bounded public HTTPS URL is required')
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or parsed.hostname not in PUBLIC_HOSTS or parsed.username is not None
            or parsed.password is not None or parsed.port is not None or parsed.query or parsed.fragment
            or any(char.isspace() for char in value) or '\\' in value):
        raise ValueError('Only reviewed public HTTPS hosts without credentials, ports, query or fragment are allowed')
    return value


def validate(job):
    fields = {'tool','operation','input','output','publication_enabled','paid_generation_enabled'}
    if not isinstance(job, dict) or set(job) != fields:
        raise ValueError('Require the exact Obscura job contract; no URL, script or launch arguments')
    if job['tool'] != 'obscura' or job['operation'] not in ('inspect-local-web-page','inspect-public-page'):
        raise ValueError('Only reviewed local or allowlisted public inspection is registered')
    if job['publication_enabled'] is not False or job['paid_generation_enabled'] is not False:
        raise ValueError('Publishing and paid generation must be explicitly false')
    for field in ('input', 'output'):
        if not isinstance(job[field], str) or not job[field]:
            raise ValueError('Explicit local paths required')
    path = no_links(job['input'])
    if not path.is_file() or path.stat().st_size > 8192:
        raise ValueError('Input must be a bounded reviewed local file')
    if job['operation']=='inspect-local-web-page':
        if digest(path) != FIXTURE_SHA256:
            raise ValueError('Input is not the reviewed self-contained page')
    else:
        request=json.loads(path.read_text())
        if not isinstance(request,dict) or set(request)!={'url'}:
            raise ValueError('Public inspection input accepts only url')
        public_url(request['url'])
    if Path(job['output']).suffix != '.json':
        raise ValueError('Obscura output must use the .json suffix')
    return path


def clean_environment(scratch, public=False):
    env = {key: os.environ[key] for key in ('PATH','LANG','SYSTEMROOT','WINDIR') if key in os.environ}
    if public:
        for key in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR'):
            if key in os.environ:env[key]=os.environ[key]
    env.update(XDG_CONFIG_HOME=str(scratch/'config'), XDG_CACHE_HOME=str(scratch/'cache'),
               PUBLICATION_ENABLED='false', PAID_GENERATION_ENABLED='false', RUST_LOG='error')
    return env


def png_metadata(path):
    if path.is_symlink() or not path.is_file() or not 100 <= path.stat().st_size <= 10 * 1024 * 1024:
        raise ValueError('Screenshot is missing or oversized')
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Screenshot is not PNG')
    cursor, compressed, dimensions, ended = 8, bytearray(), None, False
    while cursor + 12 <= len(data):
        length = struct.unpack('>I', data[cursor:cursor+4])[0]
        tag = data[cursor+4:cursor+8]; payload = data[cursor+8:cursor+8+length]
        if cursor + 12 + length > len(data) or zlib.crc32(tag+payload) & 0xffffffff != struct.unpack('>I', data[cursor+8+length:cursor+12+length])[0]:
            raise ValueError('Screenshot PNG CRC or length mismatch')
        if tag == b'IHDR':
            if dimensions is not None or len(payload) != 13:
                raise ValueError('Invalid screenshot dimensions')
            width,height,depth,color,compression,filter_method,interlace = struct.unpack('>IIBBBBB',payload)
            if (width,height) != (1280,720) or depth != 8 or color not in (2,6) or compression or filter_method or interlace:
                raise ValueError('Unexpected screenshot format')
            dimensions = {'width':width,'height':height,'color_type':color}
        elif tag == b'IDAT': compressed.extend(payload)
        elif tag == b'IEND':
            ended = length == 0 and cursor + 12 == len(data); break
        cursor += length + 12
    if not dimensions or not ended or not compressed:
        raise ValueError('Incomplete screenshot PNG')
    expected = dimensions['height'] * (1 + dimensions['width'] * (4 if dimensions['color_type']==6 else 3))
    decoder = zlib.decompressobj(); pixels = decoder.decompress(compressed, expected + 1)
    if len(pixels) != expected or not decoder.eof or decoder.unused_data:
        raise ValueError('Screenshot pixels are truncated or oversized')
    return {**dimensions, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes':len(data), 'png_verified':True}


def dispatch(job, runtime):
    page = validate(job)
    binary = verify_runtime(runtime)
    output = no_links(job['output']); screenshot = no_links(output.with_suffix('.png'))
    no_links(Path(str(output)+'.receipt.json'))
    input_sha=digest(page)
    local=job['operation']=='inspect-local-web-page'
    if output.exists() or screenshot.exists() or Path(str(output)+'.receipt.json').exists():
        raise ValueError('Use new output and screenshot paths')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='obscura-job-', dir=output.parent) as temporary:
        scratch = Path(temporary); shot = scratch/'page.png'
        uri = ('data:text/html;base64,' + base64.b64encode(page.read_bytes()).decode('ascii')
               if local else public_url(json.loads(page.read_text())['url']))
        command = [str(binary), 'fetch', uri, '--quiet', '--timeout', '10' if local else '20', '--wait', '0',
                   '--eval', EXPRESSION if local else PUBLIC_EXPRESSION, '--screenshot', str(shot)]
        with interruptible_processes(), shared_admission_lock() as lease:
            with (scratch/'stdout').open('w+b') as stdout, (scratch/'stderr').open('w+b') as stderr:
                with owned_process(command, timeout=20 if local else 30, lease_fd=lease, cwd=scratch,
                                   env=clean_environment(scratch, public=not local), stdout=stdout, stderr=stderr) as process:
                    deadline = time.monotonic() + (20 if local else 30)
                    while process.poll() is None:
                        if time.monotonic() >= deadline or max(os.fstat(stdout.fileno()).st_size,os.fstat(stderr.fileno()).st_size) > MAX_OUTPUT:
                            raise ValueError('Obscura deadline or output limit exceeded')
                        time.sleep(.02)
                    if process.returncode:
                        raise ValueError('Obscura inspection failed; no result accepted')
                if os.fstat(stderr.fileno()).st_size > MAX_OUTPUT:
                    raise ValueError('Obscura diagnostic output limit exceeded')
                stdout.seek(0); raw = stdout.read(MAX_OUTPUT+1)
                if len(raw) > MAX_OUTPUT:
                    raise ValueError('Obscura output limit exceeded')
            evaluation = json.loads(raw)
            observed = json.loads(evaluation['evaluation'])
            expected = {'title':'CYZOR private review','before':'Waiting for inspection',
                        'after':'Review ready','javascript':'javascript-ready'}
            if local:
                if not isinstance(observed, dict) or any(observed.get(key)!=value for key,value in expected.items()) or 'Publishing disabled. Paid generation disabled.' not in observed.get('text',''):
                    raise ValueError('Rendered DOM or JavaScript assertion failed')
            else:
                if (not isinstance(observed,dict) or not isinstance(observed.get('title'),str)
                        or not isinstance(observed.get('text'),str) or not observed['text'].strip()):
                    raise ValueError('No public page text was extracted')
                public_url(observed.get('url'))
            picture = png_metadata(shot)
            if digest(page) != input_sha:
                raise ValueError('Reviewed input changed during inspection')
            with screenshot.open('xb') as destination, shot.open('rb') as source:
                shutil.copyfileobj(source,destination)
    return {'schema_version':1,'status':'PASS','tool':'obscura','operation':job['operation'],
            'observed_at':datetime.now(timezone.utc).isoformat(),'upstream_revision':PIN['revision'],
            'version':PIN['version'],'archive_sha256':PIN['archive_sha256'],
            'binary_sha256':PIN['files']['obscura']['sha256'],'input_sha256':input_sha,
            'observed':observed,'screenshot':dict(picture,file=screenshot.name),
            'elapsed_seconds':time.monotonic()-started,'network_mode':('self-contained data URL; no listener or external resources' if local else 'allowlisted public HTTPS; native private-network restrictions retained'),
            'http_status_verified':False,
            'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False,
            'scope':'Bounded DOM/text and PNG inspection only; local fixture additionally verifies JavaScript mutation. HTTP status, arbitrary-site compatibility, login, media playback, rendering parity and continuous-agent operation are not attested'}
