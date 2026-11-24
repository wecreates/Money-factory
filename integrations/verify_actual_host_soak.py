"""Verify a closed actual-host soak evidence packet without claiming acceptance.

The packet must come from one authorized host and bind exact framework runs,
recovery drills and capacity observations for at least 24 hours.  This command
is read-only.  A passing packet is still subject to independent review of the
recorded useful output and host ownership; synthetic fixtures are never actual
host evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re


MAX_JSON = 4 * 1024 * 1024
MAX_REVIEWABLE_OUTPUT = 64 * 1024
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
RUN_ID = re.compile(r'^[a-z0-9][a-z0-9._-]{7,127}$')
FRAMEWORKS = ('ruflo', 'openclaw')
RUNTIME_VERSIONS = {'ruflo': '3.56.7', 'openclaw': '2026.11.6'}
DRILLS = {
    'controlled_stop': {'owned_processes_stopped': True},
    'no_orphans': {'orphan_processes': 0},
    'restart': {'fresh_run_directory': True, 'model_execution_verified': True},
    'shared_contention': {
        'second_framework_blocked': True, 'executed_tasks': 0, 'rerun_passed': True},
    'queue_recovery': {'queue_recovered': True, 'duplicate_count': 0},
    'alert_stop': {'alert_delivery_verified': True, 'stop_path_verified': True},
}
FALSE_FLAGS = {
    'publication_enabled': False,
    'paid_generation_enabled': False,
}


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key in soak evidence')
        value[key] = item
    return value


def _constant(_value):
    raise ValueError('Non-finite JSON number in soak evidence')


def _read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError('Missing or unsafe soak evidence artifact')
    raw = path.read_bytes()
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                       parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError('Soak evidence artifact must be a JSON object')
    return value, hashlib.sha256(raw).hexdigest()


def _time(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a UTC timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(f'{name} must be a UTC timestamp') from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f'{name} must be a UTC timestamp')
    return parsed


def _number(value, name, minimum=0):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < minimum):
        raise ValueError(f'{name} must be a finite number >= {minimum}')
    return value


def _false_flags(value):
    return all(value.get(key) is expected for key, expected in FALSE_FLAGS.items())


def _exact(value, expected):
    """Keep bools distinct from integers while matching receipt constants."""
    return type(value) is type(expected) and value == expected


def _identity(value, source_commit, host_fingerprint):
    if (value.get('schema_version') != 1
            or value.get('source_commit') != source_commit
            or value.get('host_fingerprint_sha256') != host_fingerprint
            or not _false_flags(value)):
        raise ValueError('Soak artifact identity or safety flags mismatch')


def _artifact(root, manifest, relative):
    if (not isinstance(relative, str) or relative.startswith('/')
            or '..' in Path(relative).parts):
        raise ValueError('Unsafe soak artifact path')
    expected = manifest['artifacts'].get(relative)
    value, actual = _read_json(root / relative)
    if not isinstance(expected, str) or not HEX64.fullmatch(expected) or actual != expected:
        raise ValueError('Soak artifact hash mismatch')
    return value


def _reviewable_output(root, manifest, relative, expected_sha):
    if (not isinstance(relative, str) or relative.startswith('/')
            or '..' in Path(relative).parts or not relative.endswith('.txt')):
        raise ValueError('Unsafe framework output artifact path')
    path = root / relative
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= MAX_REVIEWABLE_OUTPUT):
        raise ValueError('Missing or unsafe reviewable output artifact')
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if (manifest['artifacts'].get(relative) != actual or expected_sha != actual):
        raise ValueError('Framework output artifact hash mismatch')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('Framework output artifact must be UTF-8 text') from error
    if not text.strip() or '\x00' in text:
        raise ValueError('Framework output artifact is not reviewable text')


def _verify_observations(rows, started, finished, source_commit, host_fingerprint):
    if not isinstance(rows, list) or len(rows) < 25:
        raise ValueError('At least 25 hourly host observations are required')
    timestamps = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Host observation must be a JSON object')
        _identity(row, source_commit, host_fingerprint)
        observed = _time(row.get('observed_at'), 'observation observed_at')
        if not started <= observed <= finished:
            raise ValueError('Host observation lies outside the soak window')
        _number(row.get('effective_cpu_cores'), 'effective_cpu_cores', .01)
        _number(row.get('memory_available_mb'), 'memory_available_mb', 1)
        for name, minimum in (('admitted_workers', 1), ('shared_worker_ceiling', 1),
                              ('agent_processes', 1), ('queue_depth', 0),
                              ('active_workers', 0), ('orphan_workers', 0),
                              ('unexplained_failures', 0)):
            if not isinstance(row.get(name), int) or isinstance(row.get(name), bool):
                raise ValueError(f'{name} must be an integer')
            _number(row[name], name, minimum)
        if (row['orphan_workers'] != 0 or row['unexplained_failures'] != 0
                or row['shared_worker_ceiling'] != row['admitted_workers']
                or row['active_workers'] > row['admitted_workers']
                or (row['active_workers'] == 0 and row.get('idle_worker_healthy') is not True)
                or row.get('capacity_status') != 'WITHIN_BUDGET'):
            raise ValueError('Host observation records an unsafe runtime state')
        timestamps.append(observed)
    if timestamps != sorted(set(timestamps)):
        raise ValueError('Host observations must be unique and ordered')
    if timestamps[0] - started > timedelta(minutes=5):
        raise ValueError('First host observation is too late')
    if finished - timestamps[-1] > timedelta(minutes=5):
        raise ValueError('Last host observation is too early')
    if any(right - left > timedelta(hours=1) for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError('Host observation gap exceeds one hour')
    return {timestamp: row for timestamp, row in zip(timestamps, rows, strict=True)}


def _verify_framework_runs(root, manifest, observations, started, finished,
                           source_commit, host_fingerprint):
    runs = manifest.get('framework_runs')
    if not isinstance(runs, dict) or set(runs) != set(FRAMEWORKS):
        raise ValueError('Ruflo and OpenClaw run manifests are required')
    verified, referenced, run_ids, intervals = {}, [], set(), []
    for framework in FRAMEWORKS:
        paths = runs[framework]
        if not isinstance(paths, list) or len(paths) < 4 or len(set(paths)) != len(paths):
            raise ValueError('Each framework requires four distinct real run receipts')
        first_half = last_half = False
        for relative in paths:
            receipt = _artifact(root, manifest, relative)
            referenced.append(relative)
            _identity(receipt, source_commit, host_fingerprint)
            begin = _time(receipt.get('started_at'), 'framework started_at')
            end = _time(receipt.get('finished_at'), 'framework finished_at')
            capacity_time = _time(receipt.get('capacity_observed_at'),
                                  'capacity_observed_at')
            capacity = observations.get(capacity_time)
            run_id = receipt.get('run_id')
            workers = receipt.get('workers')
            if (receipt.get('kind') != 'framework_run'
                    or receipt.get('framework') != framework
                    or not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id)
                    or run_id in run_ids
                    or receipt.get('status') != 'PASS'
                    or receipt.get('runtime_version') != RUNTIME_VERSIONS[framework]
                    or receipt.get('model_execution_verified') is not True
                    or receipt.get('local_model_verified') is not True
                    or receipt.get('loopback_model_endpoint_verified') is not True
                    or receipt.get('remote_model_metadata') is not False
                    or receipt.get('cloud_model_tag') is not False
                    or receipt.get('useful_output_reviewed') is not True
                    or not isinstance(receipt.get('model_id_sha256'), str)
                    or not HEX64.fullmatch(receipt['model_id_sha256'])
                    or not isinstance(receipt.get('output_sha256'), str)
                    or not HEX64.fullmatch(receipt['output_sha256'])
                    or capacity is None
                    or not capacity_time <= begin < end <= capacity_time + timedelta(hours=1)
                    or not isinstance(workers, int) or isinstance(workers, bool)
                    or not 1 <= workers <= 8
                    or receipt.get('admitted_workers') != capacity['admitted_workers']
                    or receipt.get('shared_worker_ceiling') != capacity['shared_worker_ceiling']
                    or workers > capacity['admitted_workers']
                    or receipt.get('shared_admission_lock_verified') is not True
                    or not started <= begin < end <= finished):
                raise ValueError('Framework run receipt is incomplete or unsafe')
            run_ids.add(run_id)
            intervals.append({
                'started_at': begin,
                'finished_at': end,
                'workers': workers,
                'shared_worker_ceiling': capacity['shared_worker_ceiling'],
            })
            for name in ('input_tokens', 'output_tokens'):
                if not isinstance(receipt.get(name), int) or isinstance(receipt.get(name), bool):
                    raise ValueError(f'{name} must be an integer')
                _number(receipt[name], name, 1)
            output = receipt.get('output_artifact')
            _reviewable_output(root, manifest, output, receipt['output_sha256'])
            referenced.append(output)
            first_half |= begin <= started + timedelta(hours=2)
            last_half |= end >= finished - timedelta(hours=2)
        if not first_half or not last_half:
            raise ValueError('Each framework needs an early and late useful run')
        verified[framework] = len(paths)
    active = []
    for interval in sorted(intervals, key=lambda item: item['started_at']):
        active = [item for item in active
                  if item['finished_at'] > interval['started_at']]
        if active:
            concurrent = interval['workers'] + sum(item['workers'] for item in active)
            shared_ceiling = min([
                interval['shared_worker_ceiling'],
                *(item['shared_worker_ceiling'] for item in active),
            ])
            if concurrent > shared_ceiling:
                raise ValueError('Concurrent framework workers exceed shared ceiling')
            raise ValueError('Framework run intervals violate shared admission serialization')
        active.append(interval)
    return verified, referenced


def _verify_drills(root, manifest, started, finished, source_commit, host_fingerprint):
    drills = manifest.get('drills')
    if not isinstance(drills, dict) or set(drills) != set(DRILLS):
        raise ValueError('All controlled host drills are required')
    for drill_type, checks in DRILLS.items():
        receipt = _artifact(root, manifest, drills[drill_type])
        _identity(receipt, source_commit, host_fingerprint)
        observed = _time(receipt.get('observed_at'), 'drill observed_at')
        if (receipt.get('kind') != 'host_drill' or receipt.get('drill_type') != drill_type
                or receipt.get('status') != 'PASS' or not started <= observed <= finished
                or any(not _exact(receipt.get(key), expected)
                       for key, expected in checks.items())):
            raise ValueError('Host drill receipt is incomplete or unsafe')
    return list(drills.values())


def verify(root, expected_source_commit, *, now=None):
    supplied = Path(root)
    if supplied.is_symlink():
        raise ValueError('Soak evidence root must be a real directory')
    root = supplied.resolve(strict=True)
    if not root.is_dir() or not HEX40.fullmatch(expected_source_commit or ''):
        raise ValueError('Soak root or expected source commit is invalid')
    manifest, _manifest_sha = _read_json(root / 'soak.json')
    source_commit = manifest.get('source_commit')
    host_fingerprint = manifest.get('host_fingerprint_sha256')
    if source_commit != expected_source_commit:
        raise ValueError('Soak manifest does not match the expected source commit')
    if (manifest.get('schema_version') != 1
            or not HEX40.fullmatch(source_commit or '')
            or not HEX64.fullmatch(host_fingerprint or '') or not _false_flags(manifest)):
        raise ValueError('Unsupported or unsafe soak manifest')

    artifacts = manifest.get('artifacts')
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError('Complete soak artifact hash manifest is required')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink soak artifacts are forbidden')
        if path.is_file() and path.relative_to(root).as_posix() != 'soak.json':
            actual.add(path.relative_to(root).as_posix())
    if actual != set(artifacts):
        raise ValueError('Soak artifact set differs from manifest')
    frameworks = manifest.get('framework_runs')
    drills = manifest.get('drills')
    if not isinstance(frameworks, dict) or not isinstance(drills, dict):
        raise ValueError('Framework and drill artifact references are required')

    started = _time(manifest.get('started_at'), 'started_at')
    finished = _time(manifest.get('finished_at'), 'finished_at')
    if not timedelta(hours=24) <= finished - started <= timedelta(days=7):
        raise ValueError('Soak window must be at least 24 hours and at most seven days')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError('Verifier clock must be UTC')
    if finished > current + timedelta(minutes=5):
        raise ValueError('Soak evidence cannot finish in the future')

    observations = _verify_observations(manifest.get('observations'), started, finished,
                                        source_commit, host_fingerprint)
    runs, run_artifacts = _verify_framework_runs(
        root, manifest, observations, started, finished, source_commit, host_fingerprint)
    drill_artifacts = _verify_drills(
        root, manifest, started, finished, source_commit, host_fingerprint)
    referenced = [*run_artifacts, *drill_artifacts]
    if len(referenced) != len(set(referenced)) or set(referenced) != actual:
        raise ValueError('Every soak artifact must be referenced exactly once')
    queue = manifest.get('queue')
    required_queue = {
        'durable': True,
        'duplicate_protection_verified': True,
        'retry_recovery_verified': True,
        'resource_ceiling_enforced': True,
        'alert_delivery_verified': True,
        'stop_path_verified': True,
    }
    if (not isinstance(queue, dict)
            or any(not _exact(queue.get(k), v) for k, v in required_queue.items())):
        raise ValueError('Durable queue, recovery, limits, alerts and stop path are required')

    return {
        'status': 'PASS',
        'source_commit': source_commit,
        'host_fingerprint_sha256': host_fingerprint,
        'duration_seconds': (finished - started).total_seconds(),
        'observations': len(manifest['observations']),
        'framework_runs': runs,
        'drills': sorted(DRILLS),
        'soak_evidence_packet_verified': True,
        'actual_host_acceptance_verified': False,
        'independent_quality_review_required': True,
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'scope': ('Closed actual-host evidence packet integrity and required-gate verification only; '
                  'host ownership and useful-output quality still require independent review.'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_root')
    parser.add_argument('--expected-source-commit', required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.evidence_root, args.expected_source_commit)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        result = {
            'status': 'BLOCKED', 'reason': str(error),
            'soak_evidence_packet_verified': False,
            'actual_host_acceptance_verified': False,
            'publication_enabled': False, 'paid_generation_enabled': False,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
