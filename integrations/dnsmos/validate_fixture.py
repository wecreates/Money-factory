"""Reproduce local clean/noisy narration diagnostics, without approval thresholds.

First convert an owned isolated voice to 16kHz mono PCM16 with the README's
FFmpeg command. This helper writes only to a new directory. No media is uploaded.
"""
import argparse
import json
from pathlib import Path
import socket
import time
import wave
from unittest.mock import patch

from integrations.dnsmos.score import audio_input, model_input, score_file, sha


def validate(audio, model, output):
    data, pcm, _ = audio_input(audio, isolated_speech=True)
    model_input(model)
    import numpy as np
    original = np.frombuffer(pcm, dtype='<i2').astype(np.float64) / 32768
    if float(np.sqrt(np.mean(original * original))) <= 1e-6:
        raise ValueError('silent_fixture_forbidden')
    noise = np.random.default_rng(20261121).standard_normal(original.shape)
    noise *= np.sqrt(np.mean(original ** 2)) / np.sqrt(np.mean(noise ** 2))
    noisy = original + noise
    scale = .9 / max(np.max(np.abs(original)), np.max(np.abs(noisy)))
    folder = Path(output)
    folder.mkdir(parents=False, exist_ok=False)
    for name, signal in [('clean-normalized.wav', original), ('noisy-0db.wav', noisy)]:
        with wave.open(str(folder / name), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(np.round(signal * scale * 32767).astype('<i2').tobytes())
    def forbid(*args, **kwargs):
        raise AssertionError('network forbidden during diagnostic fixture')
    started, cpu = time.monotonic(), time.process_time()
    with patch.object(socket.socket, 'connect', forbid), patch.object(socket, 'create_connection', forbid):
        clean = score_file(folder / 'clean-normalized.wav', model, isolated_speech=True)
        degraded = score_file(folder / 'noisy-0db.wav', model, isolated_speech=True)
    if clean['status'] != 'DIAGNOSTIC_COMPLETE' or degraded['status'] != 'DIAGNOSTIC_COMPLETE':
        raise ValueError('fixture_inference_incomplete')
    measured = {'combined_wall_seconds': time.monotonic() - started,
                'combined_process_cpu_seconds': time.process_time() - cpu}
    try:
        import resource
        import sys
        if sys.platform.startswith('linux'):
            measured['process_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        pass
    measured['scope'] = 'One Python process, two sequential scores; RSS includes runtime, not a host minimum'
    proof = {
        'schema_version': 1, 'observed_at': clean['observed_at'],
        'status': 'LOCAL_DIAGNOSTIC_EXECUTION_VERIFIED',
        'host_scope': 'Current execution host only; no persistent worker or other host verified',
        'decoded_16k_mono_sha256': sha(data),
        'fixture': {'seed': 20261121, 'snr_db': 0, 'common_gain': float(scale),
                    'noise': 'NumPy default_rng standard_normal; noise RMS matched to full-clip speech RMS before common scaling',
                    'purpose': 'Controlled severe noise sensitivity check, not universal quality calibration'},
        'clean': clean, 'degraded': degraded,
        'delta_noisy_minus_clean': {key: degraded['scores'][key] - clean['scores'][key] for key in clean['scores']},
        'measurement': measured,
        'network_guard': 'Python socket connect/create_connection blocked in this smoke; adapter has no network code',
        'publication_enabled': False, 'production_approved': False, 'full_av_review': False,
        'limitations': ['Noise-suppression diagnostic does not certify TTS naturalness or artistic delivery.',
                        'Scores are observations; no approval threshold or automatic publishing decision.',
                        'Intentional music mixes must not be used as isolated speech fixtures.'],
    }
    (folder / 'runtime-proof.json').write_text(json.dumps(proof, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', required=True, help='Already converted owned isolated narration WAV')
    parser.add_argument('--model', required=True, help='Pinned local P.835 ONNX model')
    parser.add_argument('--output-dir', required=True, help='New directory, must not already exist')
    args = parser.parse_args(argv)
    proof = validate(args.audio, args.model, args.output_dir)
    print(json.dumps({'status': proof['status'], 'clean': proof['clean']['scores'],
                      'noisy': proof['degraded']['scores'], 'measurement': proof['measurement']}, indent=2))


if __name__ == '__main__':
    main()
