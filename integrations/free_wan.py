"""Bounded anonymous ZeroGPU I2V client. Never uses tokens or paid fallback."""
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

CONFIG = json.loads(Path(__file__).with_name('free-video-provider.json').read_text())
SPACE = CONFIG['space']
REVISION = CONFIG['revision']
HOST = CONFIG['host']
MAX_BYTES = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Provider redirect refused')


def request(url, data=None, content_type=None):
    headers = {'User-Agent': 'CYZOR-Free-Wan/1'}
    if content_type:
        headers['Content-Type'] = content_type
    return urllib.request.build_opener(NoRedirect).open(
        urllib.request.Request(url, data=data, headers=headers), timeout=45)


def read_json(url, data=None):
    with request(url, None if data is None else json.dumps(data).encode(),
                 None if data is None else 'application/json') as response:
        return json.loads(response.read(1024 * 1024))


def parameters(job):
    if job.get('external_processing_approved') is not True:
        raise ValueError('Explicit approval to send this image and prompt to the public ZeroGPU provider is required')
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Publication and paid generation must be explicitly disabled')
    prompt = job.get('prompt')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1200:
        raise ValueError('Prompt must contain 1–1200 characters')
    duration = job.get('duration_seconds', 1)
    if type(duration) not in (int, float) or not .3 <= duration <= 2:
        raise ValueError('Free clips are limited to 0.3–2 seconds')
    seed = job.get('seed', 42)
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Invalid seed')
    return prompt, duration, seed


def download_url(data):
    url = data[0]['video']['url']
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != urlsplit(HOST).netloc or
            not parsed.path.startswith('/gradio_api/file=') or parsed.query or parsed.fragment):
        raise ValueError('Untrusted provider output URL')
    return url


def generate(job, output):
    prompt, duration, seed = parameters(job)
    image = Path(job['input']).read_bytes()
    if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image) > 5 * 1024 * 1024:
        raise ValueError('Input must be a PNG under 5 MiB')
    metadata = read_json('https://huggingface.co/api/spaces/' + SPACE)
    runtime = metadata.get('runtime', {})
    if (metadata.get('sha') != REVISION or runtime.get('sha') != REVISION or
            runtime.get('stage') != 'RUNNING' or
            not runtime.get('hardware', {}).get('current', '').startswith('zero-')):
        raise RuntimeError('FREE_PROVIDER_UNAVAILABLE_OR_CHANGED')
    schema = read_json(HOST + '/gradio_api/info')
    names = [p['parameter_name'] for p in schema['named_endpoints']['/generate_video']['parameters']]
    if names != ['input_image', 'prompt', 'height', 'width', 'negative_prompt',
                 'duration_seconds', 'guidance_scale', 'steps', 'seed', 'randomize_seed']:
        raise RuntimeError('FREE_PROVIDER_CONTRACT_CHANGED')
    boundary = 'cyzor' + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="input.png"\r\n'
            'Content-Type: image/png\r\n\r\n').encode() + image + f'\r\n--{boundary}--\r\n'.encode()
    with request(HOST + '/gradio_api/upload', body, 'multipart/form-data; boundary=' + boundary) as response:
        uploaded = json.loads(response.read(16384))
    if not isinstance(uploaded, list) or len(uploaded) != 1 or not isinstance(uploaded[0], str):
        raise RuntimeError('INVALID_UPLOAD_RECEIPT')
    ticket = read_json(HOST + '/gradio_api/call/generate_video', {'data': [
        {'path': uploaded[0], 'meta': {'_type': 'gradio.FileData'}}, prompt,
        512, 288, 'watermark, text, distorted limbs, extra characters', duration, 1.0, 4, seed, False]})
    event_id = ticket.get('event_id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', event_id):
        raise RuntimeError('INVALID_JOB_RECEIPT')
    deadline = time.monotonic() + 180
    result = None
    event = ''
    with request(HOST + '/gradio_api/call/generate_video/' + event_id) as response:
        for line in response:
            if time.monotonic() > deadline or len(line) > 1024 * 1024:
                raise TimeoutError('FREE_PROVIDER_QUEUE_TIMEOUT')
            line = line.decode().strip()
            if line.startswith('event:'):
                event = line[6:].strip()
            elif line.startswith('data:') and event == 'error':
                raise RuntimeError('FREE_PROVIDER_ERROR: generation failed; quota/authentication cause not confirmed')
            elif line.startswith('data:') and event == 'complete':
                result = json.loads(line[5:])
                break
    if result is None:
        raise RuntimeError('FREE_PROVIDER_RETURNED_NO_RESULT')
    with request(download_url(result)) as response:
        video = response.read(MAX_BYTES + 1)
    if not video or len(video) > MAX_BYTES:
        raise RuntimeError('INVALID_VIDEO_SIZE')
    with Path(output).open('xb') as target:
        target.write(video)
    return {'provider': 'huggingface-zerogpu-anonymous', 'provider_space': SPACE,
            'provider_revision': REVISION, 'model': 'Wan2.1-I2V-14B-CausVid',
            'input_sha256': hashlib.sha256(image).hexdigest(), 'gpu_local_required': False,
            'paid_fallback': False, 'production_approved': False,
            'scope': 'Quota-limited generated asset; requires existing media and creative QA'}
