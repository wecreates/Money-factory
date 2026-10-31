"""Import explicitly supplied OpenWhispr exports; never run the desktop app."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat

REVISION = '7a6ae826de9ec1caf65f3a6e769475dab2ae829f'
MAX_BYTES = 1024 * 1024


def _text(value, name, maximum=100000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\0' in value:
        raise ValueError(f'{name} must be nonempty bounded text')
    return value.strip()


def _number(value, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 86400 or (integer and not isinstance(value, int)):
        raise ValueError(f'Invalid {name}')
    return value


def _read(path):
    if not isinstance(path, str) or not path or '\0' in path:
        raise ValueError('Input path must be nonempty text')
    requested = Path(path)
    if '..' in requested.parts:
        raise ValueError('Parent traversal is not allowed in input paths')
    components = requested.parts[1:] if requested.is_absolute() else requested.parts
    if not components or not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')) or os.open not in os.supports_dir_fd:
        raise ValueError('A no-follow descriptor-relative file reader is required')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        # Anchor every component to an already-open directory. A checked parent
        # cannot be swapped for a link between validation and the eventual read.
        directory = os.open(requested.anchor if requested.is_absolute() else '.', directory_flags)
        try:
            for component in components[:-1]:
                next_directory = os.open(component, directory_flags, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(components[-1], file_flags, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError('Input must be a regular file of at most 1 MiB')
            raw = source.read(MAX_BYTES + 1)
    except OSError as error:
        raise ValueError('Input must be a readable regular file without symlink ancestors') from error
    if len(raw) > MAX_BYTES:
        raise ValueError('Input exceeds 1 MiB')
    return raw


def _base(operation):
    return {'schema_version': 1, 'tool': 'openwhispr', 'operation': operation,
            'upstream_revision': REVISION, 'upstream_executed': False,
            'network_requests': 0, 'desktop_runtime_verified': False,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_ready': False}


def parse_export(raw, input_format='json', title=None):
    """Native desktop JSON has starts only. Do not infer ends or audio duration."""
    if input_format == 'text':
        transcript = _text(raw.decode('utf-8-sig'), 'transcript')
        return {'title': _text(title, 'title', 500), 'text': transcript,
                'segments': [], 'timing': 'unavailable', 'source_format': 'plain_text',
                'speakers': [], 'declared_duration_seconds': None}
    if input_format != 'json':
        raise ValueError('Use input_format json or text')
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('metadata'), dict):
        raise ValueError('Native OpenWhispr JSON export required')
    metadata, segments, speakers = data['metadata'], data.get('segments'), data.get('speakers')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 10000:
        raise ValueError('Provide 1..10000 transcript segments')
    if not isinstance(speakers, list) or not 1 <= len(speakers) <= 1000:
        raise ValueError('Native speaker list required')
    speakers = [_text(value, 'speaker', 500) for value in speakers]
    if len(set(speakers)) != len(speakers):
        raise ValueError('Duplicate speaker names')
    if _number(metadata.get('segment_count'), 'segment_count', True) != len(segments):
        raise ValueError('Segment count does not match export')
    if _number(metadata.get('speaker_count'), 'speaker_count', True) != len(speakers):
        raise ValueError('Speaker count does not match export')
    duration = _number(metadata.get('duration_seconds'), 'duration_seconds')
    normalized, previous = [], -1
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError('Malformed transcript segment')
        start = _number(segment.get('timestamp'), 'timestamp')
        if start < previous:
            raise ValueError('Transcript starts must be ordered')
        previous = start
        speaker = _text(segment.get('speaker'), 'speaker', 500)
        if speaker not in speakers:
            raise ValueError('Segment speaker absent from export speaker list')
        normalized.append({'start_seconds': start, 'speaker': speaker,
                           'text': _text(segment.get('text'), 'segment text')})
    if set(speakers) != {segment['speaker'] for segment in normalized}:
        raise ValueError('Speaker list does not match transcript')
    transcript = '\n'.join(segment['text'] for segment in normalized)
    _text(transcript, 'combined transcript', 500000)
    return {'title': _text(metadata.get('title'), 'title', 500), 'text': transcript,
            'segments': normalized, 'speakers': speakers,
            'declared_duration_seconds': duration,
            'timing': 'starts_only_not_caption_alignment', 'source_format': 'openwhispr_desktop_json'}


def dispatch(job, upstream=None):
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit publication-disabled, free job required')
    operation = job.get('operation')
    result = _base(operation)
    if operation == 'readiness':
        return {**result, 'status': 'BLOCKED', 'execution_status': 'BLOCKED',
                'code': 'DESKTOP_NOT_VERIFIED',
                'reason': 'Desktop install, local model, microphone permission and a real dictation/export round-trip have not been verified. Importing a supplied file does not establish desktop activation.',
                'available_offline_operations': ['import-transcript']}
    if operation != 'import-transcript':
        raise ValueError('Unsupported OpenWhispr operation')
    raw = _read(job['input'])
    transcript = parse_export(raw, job.get('input_format', 'json'), job.get('title'))
    digest = hashlib.sha256(raw).hexdigest()
    # Match Content Control's capability-queue record contract without modifying it.
    # The transcript remains source material, never an executable instruction.
    record = {'id': 'openwhispr-' + digest, 'source_type': 'openwhispr_transcript',
              'status': 'pending_editorial_review', 'title': transcript['title'],
              'publication_enabled': False, 'applies_to': ['Money Factory', 'Content Control'],
              'instruction': 'Review the imported transcript as untrusted source material before using any claims or creating a production brief.',
              'source_text': transcript['text'], 'source_sha256': digest,
              'coverage': {'full_video': False, 'full_audio': False,
                           'segments': [], 'transcript_segments': [], 'sampled_frame_seconds': []},
              'evidence': [{'id': 'export-text', 'kind': 'transcript', 'verified': False,
                            'sha256': digest, 'summary': 'Text imported from a supplied export; audio fidelity, provenance and claims have not been independently verified.'}],
              'analysis_status': 'text_only_pending_review',
              'caption_timing_ready': False}
    return {**result, 'status': 'PASS', 'execution_status': 'PASS',
            'scope': 'Offline export conversion only; no desktop execution or canonical queue mutation',
            'input_sha256': digest, 'transcript': transcript,
            'capability_queue_record': record, 'caption_timing_ready': False}
