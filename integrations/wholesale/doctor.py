"""Dependency checks and repeatable local wholesale smoke; no installation or network."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LANE = ROOT / 'integrations/wholesale'


def environment():
    keep = ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'HOME')
    return {**{k: os.environ[k] for k in keep if k in os.environ},
            'PUBLICATION_ENABLED': 'false', 'PAID_GENERATION_ENABLED': 'false',
            'PYTHONDONTWRITEBYTECODE': '1'}


def prerequisites():
    issues = []
    if sys.version_info < (3, 10):
        issues.append('PYTHON_3_10_REQUIRED: use Python 3.10 or newer')
    node = shutil.which('node')
    version = None
    if not node:
        issues.append('NODE_REQUIRED: Node 24 or newer must be available as node on PATH')
    else:
        try:
            version = subprocess.run([node, '--version'], capture_output=True, text=True,
                                     check=True, timeout=10, env=environment()).stdout.strip()
            if not version.startswith('v') or int(version[1:].split('.')[0]) < 24:
                issues.append('NODE_24_REQUIRED: use Node 24 or newer')
        except (ValueError, OSError, subprocess.SubprocessError):
            issues.append('NODE_UNUSABLE: node --version did not return a supported version')
    required = ['integrations/run.py', 'integrations/repositories.json']
    required += ['integrations/wholesale/' + name for name in (
        'worker.py', 'run.mjs', 'integration-smoke.mjs', 'onboarding.mjs',
        'listing-draft.mjs', 'offer-contract.mjs', 'engine.mjs', 'ledger.mjs',
        'pipeline.mjs', 'marketplaces.mjs', 'account-capacity.mjs',
        'sandbox-input.json', 'onboarding.example.json', 'mock-responses.json')]
    issues += ['SOURCE_FILE_MISSING: ' + name for name in required if not (ROOT / name).is_file()]
    return {'python': sys.version.split()[0], 'node': version, 'errors': issues}


def execute(output_dir=None, config=None, check_only=False):
    report = {'status': 'DEPENDENCY_CHECK_FAILED', 'scope': 'offline wholesale only',
              'publication_enabled': False, 'dispatch_enabled': False,
              'provider_validated': False, 'production_ready': False,
              'dependencies': prerequisites(), 'operations': [],
              'external_inputs_required': ['Supplier/channel/SKU agreement and product provenance',
                  'Permitted current feed and dated delivered-cost quote',
                  'Shipping origin, returns terms and licensed product assets',
                  'Seller account limits, policies and separately approved API access']}
    if report['dependencies']['errors']:
        return report, 1
    if config is not None:
        config = Path(config).resolve()
        try:
            value = json.loads(config.read_text(encoding='utf-8-sig'))
            if not isinstance(value, dict) or type(value.get('now')) is not int or value['now'] < 0:
                raise ValueError()
            if value.get('mode') != 'sandbox' or value.get('live_enabled') is not False:
                raise ValueError()
        except (OSError, ValueError):
            report.update(status='CONFIG_INVALID', error='Provide readable JSON object with explicit nonnegative integer now, mode=sandbox and live_enabled=false; no input values echoed')
            return report, 1
    if check_only:
        report['status'] = 'DEPENDENCIES_OK_SMOKE_NOT_RUN'
        return report, 0
    try:
        if output_dir is None:
            destination = Path(tempfile.mkdtemp(prefix='wholesale-offline-'))
        else:
            destination = Path(output_dir).resolve()
            destination.mkdir(parents=True, exist_ok=False)
    except OSError:
        report.update(status='OUTPUT_DIRECTORY_UNAVAILABLE', error='Use a new writable output directory; existing paths are never reused')
        return report, 1
    report['output_directory'] = str(destination)
    scenarios = [(op, LANE / source, op) for op, source in [
        ('dry-run', 'sandbox-input.json'), ('integration-dry-run', 'sandbox-input.json'),
        ('onboarding-check', 'onboarding.example.json'), ('listing-draft', 'onboarding.example.json'),
        ('offer-contract', 'onboarding.example.json')]]
    if config is not None:
        scenarios.append(('onboarding-check', config, 'supplied-config'))
    for operation, source, label in scenarios:
        output = destination / (label + '.json')
        job_path = destination / (label + '.job.json')
        job = dict(tool='wholesale', operation=operation, mode='sandbox', input=str(source),
                   output=str(output), publication_enabled=False, paid_generation_enabled=False, live_enabled=False)
        job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
        try:
            subprocess.run([sys.executable, str(ROOT / 'integrations/run.py'), str(job_path),
                            '--runtime', str(destination / 'runtime')], cwd=ROOT, env=environment(),
                           capture_output=True, text=True, check=True, timeout=90)
            result = json.loads(output.read_text(encoding='utf-8'))
            receipt = json.loads(Path(str(output) + '.receipt.json').read_text(encoding='utf-8'))
            if receipt.get('status') != 'PASS' or receipt.get('output_sha256') != hashlib.sha256(output.read_bytes()).hexdigest():
                raise ValueError('RECEIPT_INVALID')
            if result.get('publication_enabled') is not False or result.get('orders_placed') != 0:
                raise ValueError('UNSAFE_RESULT')
            if label == 'dry-run' and [o['state'] for o in result['state']['orders']] != ['refunded', 'cancelled', 'accepted']:
                raise ValueError('SCENARIO_MISMATCH')
            if label == 'integration-dry-run' and (result.get('classification') != 'AUTHORED_MOCK_INTEGRATION' or len(result['state']['orders']) != 3):
                raise ValueError('SCENARIO_MISMATCH')
            if label in ('onboarding-check', 'listing-draft', 'offer-contract') and result.get('status') != 'BLOCKED':
                raise ValueError('FIXTURE_READINESS_MISMATCH')
            report['operations'].append({'operation': label, 'execution': 'PASS',
                'readiness': result.get('status', 'SYNTHETIC_ONLY'), 'report': str(output),
                'blocker_codes': sorted({b['code'] for b in result.get('blockers', [])})})
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            report.update(status='OFFLINE_SMOKE_FAILED', failed_operation=label,
                          error='Worker execution or receipt/scenario validation failed; partial outputs retained, no success claimed')
            break
    else:
        report['status'] = 'OFFLINE_SMOKE_PASSED_PRODUCTION_BLOCKED'
    (destination / 'doctor-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report, 0 if report['status'] == 'OFFLINE_SMOKE_PASSED_PRODUCTION_BLOCKED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', help='New directory only; default creates a unique retained OS temporary directory')
    parser.add_argument('--config', help='Optional private offline onboarding JSON; no credentials are required')
    parser.add_argument('--check-only', action='store_true', help='Check dependencies/config syntax only, without running scenarios')
    args = parser.parse_args()
    result, code = execute(args.output_dir, args.config, args.check_only)
    print(json.dumps(result, indent=2))
    sys.exit(code)
