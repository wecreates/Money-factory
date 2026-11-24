"""Retain revision handoffs without claiming independent parent verification."""
import hashlib
import json
import os
from pathlib import Path

from integrations.content_control.review_package import no_symlinks, require, SHA

LIMIT = 64 * 1024
FLAGS = ('publication_enabled', 'paid_generation_enabled', 'production_approved',
         'full_av_review', 'production_ready', 'feedback_resolution_verified')
HASHES = ('supersedes_candidate_sha256', 'recorded_review_sha256',
          'prior_cycle_sha256', 'brief_sha256')
SCOPE = ('Exact supplied revision handoff retained; parent artifacts and review are not '
         'independently revalidated here, and feedback resolution is not verified.')
RECEIPT_FIELDS = {'schema_version', 'status', 'feedback', 'scope', *FLAGS, *HASHES}
DISCOVERY_RECEIPT_FIELD = 'topic_discovery_sha256'
LINEAGE_FIELDS = {'schema_version', 'revision_json', 'revision_sha256',
                  'parent_evidence_independently_verified', 'feedback_resolution_verified', 'scope'}


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate revision JSON key')
        value[key] = item
    return value


def _constant(value):
    raise ValueError('Nonfinite revision JSON value')


def validate_lineage(value, expected_brief_sha256):
    """Validate retained handoff bytes and their current-brief binding only."""
    require(isinstance(value, dict) and set(value) == LINEAGE_FIELDS, 'Invalid revision lineage fields')
    require(type(value.get('schema_version')) is int and value['schema_version'] == 1,
            'Revision lineage schema mismatch')
    require(value.get('parent_evidence_independently_verified') is False and
            value.get('feedback_resolution_verified') is False and value.get('scope') == SCOPE,
            'Revision lineage must not claim independent verification')
    raw = value.get('revision_json')
    require(isinstance(raw, str), 'Revision JSON text required')
    try:
        encoded = raw.encode('utf-8')
    except UnicodeError as error:
        raise ValueError('Revision JSON must be valid UTF-8') from error
    require(len(encoded) <= LIMIT, 'Revision handoff exceeds 64 KiB')
    require(hashlib.sha256(encoded).hexdigest() == value.get('revision_sha256'), 'Revision handoff hash mismatch')
    receipt = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(receipt, dict)
            and ((type(receipt.get('schema_version')) is int
                  and receipt['schema_version'] == 1 and set(receipt) == RECEIPT_FIELDS)
                 or (type(receipt.get('schema_version')) is int
                     and receipt['schema_version'] == 2
                     and set(receipt) == RECEIPT_FIELDS | {DISCOVERY_RECEIPT_FIELD}))
            and receipt.get('status') == 'REVISION_BRIEF_READY',
            'Invalid revision receipt fields or schema/status')
    if receipt['schema_version'] == 2:
        require(isinstance(receipt[DISCOVERY_RECEIPT_FIELD], str)
                and SHA.fullmatch(receipt[DISCOVERY_RECEIPT_FIELD]),
                'Invalid revision discovery identity')
    require(all(receipt.get(flag) is False for flag in FLAGS), 'Revision flags must remain false')
    require(all(isinstance(receipt.get(key), str) and SHA.fullmatch(receipt[key]) for key in HASHES),
            'Invalid revision identity')
    require(receipt['brief_sha256'] == expected_brief_sha256, 'Revision targets a different brief')
    feedback = receipt.get('feedback')
    require(isinstance(feedback, list) and len(feedback) <= 6, 'Invalid revision feedback')
    for item in feedback:
        require(isinstance(item, dict) and set(item) == {'check', 'action'} and
                isinstance(item['check'], str) and 1 <= len(item['check']) <= 80 and
                isinstance(item['action'], str) and 1 <= len(item['action']) <= 4000,
                'Invalid revision feedback entry')
    require(receipt.get('scope') == 'Revised supplied brief; previous approval statements cannot certify a new render.',
            'Revision receipt scope mismatch')
    return receipt


def read_revision(path, expected_brief_sha256):
    path = Path(os.path.abspath(path))
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= LIMIT, 'Missing or oversized revision handoff')
    try:
        raw = path.read_bytes().decode('utf-8')
    except UnicodeError as error:
        raise ValueError('Revision handoff must be valid UTF-8') from error
    value = {'schema_version': 1, 'revision_json': raw,
             'revision_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
             'parent_evidence_independently_verified': False, 'feedback_resolution_verified': False,
             'scope': SCOPE}
    validate_lineage(value, expected_brief_sha256)
    return value
