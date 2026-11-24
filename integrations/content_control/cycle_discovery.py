"""Select a sourced topic from an externally observed candidate pool.

This offline boundary never fetches sources, measures audience demand, or writes
a script.  It makes the first autonomous-cycle decision deterministic and
replayable so the selected research can enter ``cycle_intake`` unchanged.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

from integrations.content_control.cycle_editorial import FALSE_FLAGS, compile_editorial, _timestamp
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _regular
from integrations.content_control.review_package import no_symlinks, require

MAX_POOL = 96 * 1024
MAX_RECEIPT = 128 * 1024
MAX_POOL_AGE = timedelta(hours=24)
MAX_EVIDENCE_AGE = timedelta(days=30)
DOMAIN_NORMALIZATION = 'lowercase IDNA host; IP rejected; last two labels, or last three for bounded common two-label suffixes'
FRESHNESS_POLICY = {'pool_max_age_seconds': int(MAX_POOL_AGE.total_seconds()),
                    'evidence_max_age_seconds': int(MAX_EVIDENCE_AGE.total_seconds())}
TWO_LABEL_SUFFIXES = frozenset({
    'co.uk', 'org.uk', 'gov.uk', 'ac.uk', 'com.au', 'net.au', 'org.au',
    'co.jp', 'co.nz', 'com.br', 'com.mx', 'co.in', 'com.sg', 'com.tr',
})


def _read(path, limit):
    with _regular(Path(path), limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Discovery input exceeds its byte limit')
    return raw


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _registrable_domain(url):
    host = urlsplit(url).hostname.lower().rstrip('.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.encode('idna').decode('ascii').split('.')
        require(len(labels) >= 2, 'Evidence URL requires a registrable-looking domain')
        suffix = '.'.join(labels[-2:])
        size = 3 if suffix in TWO_LABEL_SUFFIXES and len(labels) >= 3 else 2
        return '.'.join(labels[-size:])
    raise ValueError('IP addresses cannot establish independent source domains')


def _candidate(candidate, pool_at):
    fields = {'id', 'topic', 'sources', 'reference_observations'}
    require(isinstance(candidate, dict) and set(candidate) == fields,
            'Discovery candidate requires exact topic evidence fields')
    identifier = candidate['id']
    require(isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', identifier),
            'Discovery candidate requires a safe ID')
    flags = dict.fromkeys(FALSE_FLAGS, False)
    probe = {'schema_version': 1, 'title': 'Discovery evidence probe',
             'topic': candidate['topic'], 'sources': candidate['sources'],
             'reference_observations': candidate['reference_observations'],
             'scenes': [{'id': 'probe', 'narration': 'Evidence boundary probe.',
                         'visual': 'No authored production scene.', 'source_ids': [],
                         'factual': False, 'speaker': 'narrator', 'duration_seconds': 1}], **flags}
    editorial = compile_editorial(probe)
    source_domains = sorted({_registrable_domain(source['url']) for source in editorial['sources']})
    all_domains = sorted({*source_domains,
                          *(_registrable_domain(item['url']) for item in editorial['reference_observations'])})
    require(len(source_domains) >= 2,
            'Discovery candidate requires at least two registrable source domains')
    source_times = [datetime.fromisoformat(source['retrieved_at']) for source in editorial['sources']]
    reference_times = [datetime.fromisoformat(item['observed_at'])
                       for item in editorial['reference_observations']]
    evidence_times = source_times + reference_times
    require(max(evidence_times) <= pool_at, 'Candidate evidence cannot be newer than the candidate pool')
    require(min(evidence_times) >= pool_at - MAX_EVIDENCE_AGE,
            'Candidate evidence exceeds the bounded freshness window')
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    mean_time = epoch + sum((item - epoch for item in evidence_times), timedelta()) / len(evidence_times)
    research = {'schema_version': 1, 'topic': editorial['topic'],
                'sources': editorial['sources'],
                'reference_observations': editorial['reference_observations']}
    score = {'distinct_source_registrable_domains': len(source_domains),
             'distinct_all_evidence_registrable_domains': len(all_domains),
             'evidence_timestamp_count': len(evidence_times),
             'oldest_evidence_at': min(evidence_times).astimezone(timezone.utc).isoformat(),
             'mean_evidence_at': mean_time.astimezone(timezone.utc).isoformat(),
             'newest_evidence_at': max(evidence_times).astimezone(timezone.utc).isoformat()}
    return identifier, research, score


def _select(pool_raw, selected_at):
    pool = json.loads(pool_raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(pool, dict) and set(pool) == {'schema_version', 'created_at', 'candidates'}
            and type(pool['schema_version']) is int and pool['schema_version'] == 1,
            'Unexpected discovery pool fields or schema version')
    created = datetime.fromisoformat(_timestamp(pool['created_at'], 'discovery.created_at'))
    selected = datetime.fromisoformat(_timestamp(selected_at, 'discovery.selected_at'))
    require(timedelta(0) <= selected - created <= MAX_POOL_AGE,
            'Candidate pool must be selected within the bounded freshness window')
    require(isinstance(pool['candidates'], list) and 2 <= len(pool['candidates']) <= 40,
            'Discovery pool requires 2–40 candidates')
    candidates = [_candidate(item, created) for item in pool['candidates']]
    identifiers = [item[0] for item in candidates]
    topics = [item[1]['topic'].casefold() for item in candidates]
    require(len(identifiers) == len(set(identifiers)), 'Discovery candidate IDs must be unique')
    require(len(topics) == len(set(topics)), 'Discovery candidate topics must be unique')
    ordered = sorted(candidates, key=lambda item: (-item[2]['distinct_source_registrable_domains'],
                                                    -item[2]['distinct_all_evidence_registrable_domains'],
                                                    -datetime.fromisoformat(item[2]['oldest_evidence_at']).timestamp(),
                                                    -datetime.fromisoformat(item[2]['mean_evidence_at']).timestamp(),
                                                    -datetime.fromisoformat(item[2]['newest_evidence_at']).timestamp(),
                                                    item[0]))
    chosen = ordered[0]
    research_raw = _json_bytes(chosen[1])
    flags = dict.fromkeys(FALSE_FLAGS, False)
    receipt = {'schema_version': 1, 'status': 'SOURCED_TOPIC_SELECTED', **flags,
               'selected_at': selected_at, 'pool_created_at': created.isoformat(),
               'pool_sha256': hashlib.sha256(pool_raw).hexdigest(),
               'research_sha256': hashlib.sha256(research_raw).hexdigest(),
               'selected_candidate_id': chosen[0], 'selection_basis': chosen[2],
               'domain_normalization': DOMAIN_NORMALIZATION,
               'freshness_policy': FRESHNESS_POLICY,
               'candidate_order': [item[0] for item in ordered],
               'scope': ('Deterministic source-domain coverage and evidence-recency selection only. '
                         'No trend, popularity, factual accuracy, authorship or creative approval claim.')}
    return research_raw, _json_bytes(receipt), receipt


def select_topic(pool_path, output):
    """Select one candidate and retain exact research and replay receipt bytes."""
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    pool_path, output = Path(os.path.abspath(pool_path)), Path(os.path.abspath(output))
    no_symlinks(output)
    require(not output.exists(), 'Fresh discovery output directory required')
    pool_raw = _read(pool_path, MAX_POOL)
    selected_at = datetime.now(timezone.utc).isoformat()
    research_raw, receipt_raw, receipt = _select(pool_raw, selected_at)
    require(_read(pool_path, MAX_POOL) == pool_raw, 'Discovery pool changed during selection')
    output.mkdir(parents=True, exist_ok=False)
    try:
        with (output / 'research.json').open('xb') as stream:
            stream.write(research_raw)
        with (output / 'discovery.json').open('xb') as stream:
            stream.write(receipt_raw)
    except BaseException:
        shutil.rmtree(output)
        raise
    return receipt


def verify_inline_selection(pool_raw, research_raw, receipt_raw):
    """Replay exact discovery bytes for intake and durable queue consumers."""
    require(all(isinstance(value, bytes) for value in (pool_raw, research_raw, receipt_raw)),
            'Discovery replay requires exact bytes')
    require(0 < len(pool_raw) <= MAX_POOL and 0 < len(research_raw) <= MAX_POOL
            and 0 < len(receipt_raw) <= MAX_RECEIPT, 'Discovery replay exceeds byte limits')
    receipt = json.loads(receipt_raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(receipt, dict), 'Invalid discovery receipt')
    selected_at = _timestamp(receipt.get('selected_at'), 'discovery.selected_at')
    expected_research, expected_receipt, expected = _select(pool_raw, selected_at)
    require(research_raw == expected_research, 'Selected research does not match the candidate pool')
    require(receipt_raw == expected_receipt, 'Discovery receipt does not match the candidate pool')
    return {'schema_version': 1, 'status': 'DISCOVERY_VERIFIED', **dict.fromkeys(FALSE_FLAGS, False),
            'selected_at': selected_at, 'pool_created_at': expected['pool_created_at'],
            'pool_sha256': expected['pool_sha256'], 'research_sha256': expected['research_sha256'],
            'discovery_receipt_sha256': hashlib.sha256(receipt_raw).hexdigest(),
            'selected_candidate_id': expected['selected_candidate_id'],
            'selection_basis': expected['selection_basis'],
            'domain_normalization': DOMAIN_NORMALIZATION,
            'freshness_policy': FRESHNESS_POLICY, 'scope': expected['scope']}


def verify_selection(pool_path, output):
    """Replay an existing selection without changing its files."""
    pool_path, output = Path(os.path.abspath(pool_path)), Path(os.path.abspath(output))
    pool_raw = _read(pool_path, MAX_POOL)
    research_path, receipt_path = output / 'research.json', output / 'discovery.json'
    research_raw, receipt_raw = _read(research_path, MAX_POOL), _read(receipt_path, MAX_RECEIPT)
    proof = verify_inline_selection(pool_raw, research_raw, receipt_raw)
    require(_read(pool_path, MAX_POOL) == pool_raw and _read(research_path, MAX_POOL) == research_raw
            and _read(receipt_path, MAX_RECEIPT) == receipt_raw,
            'Discovery evidence changed while verifying')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output')
    mode.add_argument('--verify')
    args = parser.parse_args()
    result = verify_selection(args.pool, args.verify) if args.verify else select_topic(args.pool, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
