"""Collect candidate-bound audio observations from a model on this machine."""

import argparse
import base64
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import wave

RATE = 16000
WINDOW = 12 * RATE
PROMPT = ('Listen to this exact clip. Give three short lines labeled VOICE (naturalness, phrasing '
          'or unclear words), SOUND (music or effects distinct from speech), and MIX (masking '
          'or distracting pauses). Mention a clip-relative time for a concrete repair or say '
          'uncertain. Do not use a transcript or assume a defect.')
PENDING = {'independent_listening_verification': False, 'full_av_review': False,
           'production_approved': False, 'publication_enabled': False, 'paid_generation_enabled': False}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def query_audio(wav, prompt, model, port):
    """Send WAV bytes only to the selected local loopback port."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid local port')
    request = Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                      headers={'Content-Type': 'application/json'}, data=json.dumps({
        'model': model, 'stream': False, 'temperature': 0, 'max_tokens': 80,
        'reasoning_format': 'none',
        'messages': [{'role': 'user', 'content': [
            {'type': 'input_audio', 'input_audio': {
                'data': base64.b64encode(wav).decode('ascii'), 'format': 'wav'}},
            {'type': 'text', 'text': prompt},
        ]}],
    }).encode())
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=180) as response:
        body = response.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError('Oversized local model response')
    choice = json.loads(body)['choices'][0]
    observation = choice['message']['content']
    if not isinstance(observation, str) or not observation.strip():
        raise ValueError('The local model returned no observation')
    return {'observation': observation.strip(), 'finish_reason': choice.get('finish_reason')}


def wav_bytes(samples):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        audio.writeframes(samples)
    return stream.getvalue()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def decode_program(video):
    """Decode zero-start mono audio on the container's playback clock."""
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-f', 'mov',
        '-select_streams', 'a:0',
        '-show_entries', 'stream=channels,start_time,duration:format=start_time,duration',
        '-of', 'json', str(video)], timeout=30))
    stream, = probe['streams']
    program = probe['format']
    duration = Fraction(program['duration'])
    if (stream['channels'] != 1 or Fraction(program.get('start_time', '0')) != 0
            or Fraction(stream.get('start_time', '0')) != 0 or not 0 < duration <= 900
            or abs(Fraction(stream['duration']) - duration) > Fraction(1, 8)):
        raise ValueError('This listening path requires a bounded, zero-start mono program')
    samples = round(duration * RATE)
    decoded = subprocess.check_output([
        'ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-protocol_whitelist', 'file,pipe',
        '-f', 'mov', '-i', str(video),
        '-map', '0:a:0',
        '-af', f'aresample={RATE}:async=1:first_pts=0,apad,atrim=end_sample={samples},asetpts=N/SR/TB',
        '-ar', str(RATE), '-f', 's16le', 'pipe:1'], timeout=120)
    if not samples or len(decoded) != 2 * samples:
        raise ValueError('Decoded audio does not match the measured playback span')
    return decoded


def needs_followup(response):
    if response.get('finish_reason') != 'stop':
        return True
    text = response['observation'].replace('<think></think>', '').strip()
    fields = re.findall(r'^\s*(VOICE|SOUND|MIX)\s*:\s*(.+)$', text, flags=re.M | re.I)
    return ({label.upper() for label, _ in fields} != {'VOICE', 'SOUND', 'MIX'}
            or len(fields) != 3 or any(len(value.strip()) < 3 for _, value in fields))


def record(video, caption, output, *, video_sha256, caption_sha256, model, port):
    """Retain observations and measured coverage as JSONL without approval."""
    if any(os.environ.get(key, 'false').lower() != 'false'
           for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')):
        raise ValueError('Publishing and paid inference must remain disabled')
    if not model or len(model) > 120 or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('A bounded model name and local port are required')
    video, caption, output = map(Path, (video, caption, output))
    if (not video.is_file() or not 0 < video.stat().st_size <= 256 * 1024 * 1024
            or not caption.is_file() or not 0 < caption.stat().st_size <= 1024 * 1024):
        raise ValueError('A bounded video and caption file are required')
    identity = {'candidate_sha256': video_sha256, 'caption_sha256': caption_sha256}

    def check_sources():
        if not all(re.fullmatch(r'[a-f0-9]{64}', expected) and digest(path) == expected
                   for path, expected in ((video, video_sha256), (caption, caption_sha256))):
            raise ValueError('Video or caption SHA-256 mismatch')

    check_sources()
    pcm = decode_program(video.resolve())
    check_sources()
    if not pcm or len(pcm) % 2:
        raise ValueError('PCM must contain whole samples and at least one sample')
    end_sample = len(pcm) // 2
    with output.open('x', encoding='utf-8') as stream:
        def emit(item):
            stream.write(json.dumps(item, allow_nan=False) + '\n')
            stream.flush()

        emit({'status': 'LOCAL_MODEL_OBSERVATIONS_STARTED', **identity, **PENDING,
              'model': model, 'sample_rate_hz': RATE, 'program_samples': end_sample})
        followups = 0
        for start in range(0, end_sample, WINDOW):
            end = min(end_sample, start + WINDOW)
            context_start = max(0, start - RATE)
            context_end = min(end_sample, end + RATE)
            wav = wav_bytes(pcm[2 * context_start:2 * context_end])
            response = query_audio(wav, PROMPT, model, port)
            followup = needs_followup(response)
            followups += followup
            emit({'start_sample': start, 'end_sample': end, 'clip_start_sample': context_start,
                  'clip_end_sample': context_end, 'wav_sha256': hashlib.sha256(wav).hexdigest(),
                  'format_followup_required': followup,
                  **response})
        check_sources()
        emit({'status': 'LOCAL_MODEL_OBSERVATIONS_RECORDED', **identity, **PENDING,
              'program_samples': end_sample, 'format_followup_count': followups})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('video', 'caption', 'output', 'video-sha256', 'caption-sha256', 'model'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, default=8791)
    record(**vars(parser.parse_args()))


if __name__ == '__main__':
    main()
