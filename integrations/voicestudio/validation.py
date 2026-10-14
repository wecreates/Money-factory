"""Technical PCM acceptance, independent of model return status."""
from array import array
import math
from pathlib import Path
import sys
import wave


def validate_audio(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Unlinked audio output required')
    with wave.open(str(path), 'rb') as audio:
        channels, width, rate, count = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
        if channels != 1 or width != 2 or rate != 24000 or not 0.25 <= count / rate <= 180:
            raise ValueError('Expected bounded 24 kHz mono PCM16 speech')
        raw = audio.readframes(count)
    if len(raw) != count * 2:
        raise ValueError('Truncated audio output')
    samples = array('h', raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    rms = math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / count)
    clipped = sum(abs(sample) >= 32760 for sample in samples) / count
    if rms < 0.00001 or clipped > 0.01:
        raise ValueError('Silent or excessively clipped audio output')
    return {'duration_seconds': count / rate, 'sample_rate': rate, 'channels': channels,
            'sample_width_bytes': width, 'rms': rms, 'clipped_fraction': clipped,
            'scope': 'Technical waveform validation; not listening or pronunciation approval'}
