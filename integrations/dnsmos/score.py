"""Local DNSMOS P.835 diagnostics for explicitly identified isolated narration.

Adapted from Microsoft's dnsmos_local.py at the revision below (CC-BY-4.0).
This module performs no downloads, uploads, publishing or approval decisions.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
import wave

UPSTREAM_REVISION = '785ab12275d5cf9341c5e946b0eee9f8825ece3b'
MODEL_SHA256 = '269fbebdb513aa23cddfbb593542ecc540284a91849ac50516870e1ac78f6edd'
MODEL_BYTES = 1157965
SAMPLE_RATE = 16000
WINDOW_SAMPLES = 144160  # 9.01 seconds, matching the upstream P.835 model.
MAX_SECONDS = 120
SCOPE = ('No-reference speech/noise diagnostic on operator-identified isolated narration; '
         'not a listening test, TTS naturalness assessment, music-mix judgment, '
         'audiovisual synchronization check or creative/production approval.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_bounded(path, maximum):
    with Path(path).open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('input_size_limit')
    return data


def audio_input(path, *, isolated_speech):
    if isolated_speech is not True:
        raise ValueError('explicit_isolated_speech_assertion_required')
    data = read_bounded(path, MAX_SECONDS * SAMPLE_RATE * 2 + 65536)
    with wave.open(io.BytesIO(data), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, SAMPLE_RATE, 'NONE'):
            raise ValueError('require_16khz_mono_pcm16_wav')
        count = wav.getnframes()
        if not WINDOW_SAMPLES <= count <= MAX_SECONDS * SAMPLE_RATE:
            raise ValueError('require_9_01_to_120_seconds')
        pcm = wav.readframes(count)
        if len(pcm) != count * 2:
            raise ValueError('truncated_audio')
    return data, pcm, count


def model_input(path):
    data = read_bounded(path, MODEL_BYTES)
    if len(data) != MODEL_BYTES or sha(data) != MODEL_SHA256:
        raise ValueError('pinned_model_identity_mismatch')
    return data


def calibrated(raw):
    # Regular, non-personalized P.835 calibration, copied from upstream.
    sig, bak, ovr = map(float, raw)
    values = {
        'SIG': -0.08397278 * sig * sig + 1.22083953 * sig + 0.0052439,
        'BAK': -0.13166888 * bak * bak + 1.60915514 * bak - 0.39604546,
        'OVRL': -0.06766283 * ovr * ovr + 1.11546468 * ovr + 0.04602535,
    }
    if not all(math.isfinite(v) for v in (*raw, *values.values())):
        raise ValueError('nonfinite_model_output')
    return values


def score_file(audio_path, model_path, *, isolated_speech=False):
    started = time.monotonic()
    report = {
        'schema_version': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'status': 'BLOCKED', 'scope': SCOPE, 'engine': 'DNSMOS-P835-local-CPU',
        'source_revision': UPSTREAM_REVISION, 'model_sha256': MODEL_SHA256,
        'model_license': 'CC-BY-4.0', 'publication_enabled': False,
        'paid_generation_enabled': False, 'production_approved': False,
        'full_av_review': False, 'isolated_speech_asserted_by_operator': isolated_speech is True,
        'network_requests_by_adapter': 0, 'onnx_intra_op_threads': 1,
        'onnx_inter_op_threads': 1, 'max_input_seconds': MAX_SECONDS,
    }
    try:
        audio, pcm, count = audio_input(audio_path, isolated_speech=isolated_speech)
        model = model_input(model_path)
        import numpy as np
        import onnxruntime as ort
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        if float(np.sqrt(np.mean(samples * samples))) <= 1e-6:
            raise ValueError('silent_input_not_speech_quality_evidence')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        # Bytes prevent a file replacement between hash verification and load.
        session = ort.InferenceSession(model, sess_options=options, providers=['CPUExecutionProvider'])
        windows = []
        for start in range(0, count - WINDOW_SAMPLES + 1, SAMPLE_RATE):
            segment = samples[start:start + WINDOW_SAMPLES][None, :]
            raw = session.run(None, {'input_1': segment})[0][0]
            if len(raw) != 3:
                raise ValueError('unexpected_model_output_shape')
            windows.append({'start_seconds': start / SAMPLE_RATE,
                            'end_seconds': (start + WINDOW_SAMPLES) / SAMPLE_RATE,
                            'raw': dict(zip(('SIG', 'BAK', 'OVRL'), map(float, raw))),
                            'scores': calibrated(raw)})
        report.update(status='DIAGNOSTIC_COMPLETE', audio_sha256=sha(audio),
                      duration_seconds=count / SAMPLE_RATE, sample_rate=SAMPLE_RATE,
                      channels=1, window_count=len(windows), windows=windows,
                      unscored_tail_seconds=(count / SAMPLE_RATE - windows[-1]['end_seconds']),
                      scores={key: sum(w['scores'][key] for w in windows) / len(windows)
                              for key in ('SIG', 'BAK', 'OVRL')},
                      providers=session.get_providers(),
                      runtime_versions={'onnxruntime': ort.__version__, 'numpy': np.__version__})
    except (OSError, ValueError, wave.Error, EOFError, ImportError) as error:
        report['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
    except Exception as error:
        # ORT native failures are not RuntimeError. Other programming errors,
        # KeyboardInterrupt and SystemExit must still propagate.
        if not type(error).__module__.startswith('onnxruntime.'):
            raise
        report['blocker'] = 'onnxruntime_' + type(error).__name__
    report['elapsed_seconds'] = round(time.monotonic() - started, 6)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', required=True, help='Local 16kHz mono PCM16 narration WAV, 9.01..120 seconds')
    parser.add_argument('--model', required=True, help='Already downloaded, pinned sig_bak_ovr.onnx')
    parser.add_argument('--isolated-speech', action='store_true', help='Assert this is isolated narration, not a final music mix')
    args = parser.parse_args(argv)
    report = score_file(args.audio, args.model, isolated_speech=args.isolated_speech)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'DIAGNOSTIC_COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
