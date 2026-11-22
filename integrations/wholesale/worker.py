"""Existing Money Factory worker bridge. Local sandbox only, no credentials inherited."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def dispatch(job, root):
    if job.get('operation') not in ('dry-run', 'integration-dry-run', 'onboarding-check', 'listing-draft', 'offer-contract') or job.get('mode') != 'sandbox':
        raise ValueError('Wholesale worker supports sandbox dry-run only')
    for flag in ('publication_enabled', 'paid_generation_enabled', 'live_enabled'):
        if job.get(flag) is not False:
            raise ValueError('Wholesale execution flags must explicitly be false')
    source = Path(job['input']).resolve(strict=True)
    output = Path(job['output']).resolve()
    receipt_path = Path(str(output) + '.receipt.json')
    if output.exists() or receipt_path.exists():
        raise ValueError('Output or receipt already exists')
    # The Node CLI performs exclusive creation; concurrent jobs cannot overwrite.
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = {k: os.environ[k] for k in ('PATH','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP','HOME') if k in os.environ}
    environment.update(PUBLICATION_ENABLED='false', PAID_GENERATION_ENABLED='false')
    scripts = {'dry-run':'run.mjs','integration-dry-run':'integration-smoke.mjs','onboarding-check':'onboarding.mjs','listing-draft':'listing-draft.mjs','offer-contract':'offer-contract.mjs'}
    script = root / 'integrations/wholesale' / scripts[job['operation']]
    # Capture once, then execute a private per-job snapshot, never the mutable
    # source path. The worker never modifies the snapshot while the CLI runs.
    source_bytes = source.read_bytes()
    with tempfile.TemporaryDirectory(prefix='wholesale-input-') as snapshot_directory:
        snapshot = Path(snapshot_directory) / 'input.json'
        with snapshot.open('xb') as handle:
            handle.write(source_bytes)
        subprocess.run(['node', str(script), str(snapshot), str(output)], cwd=root,
                       env=environment, capture_output=True, text=True, check=True, timeout=60)
        if snapshot.read_bytes() != source_bytes:
            raise ValueError('Input snapshot changed; no receipt issued')
    output_bytes = output.read_bytes()
    result = json.loads(output_bytes.decode('utf-8'))
    if result.get('mode') != 'sandbox' or result.get('orders_placed') != 0 or result.get('publication_enabled') is not False:
        raise ValueError('Invalid wholesale sandbox result')
    receipt = {'schema_version':1, 'tool':'wholesale', 'operation':job['operation'],
               'status':'PASS', 'mode':'sandbox', 'scope':'Local simulation only; not authenticated provider validation',
               'verified_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
               'output_sha256':hashlib.sha256(output_bytes).hexdigest(),
               'input_sha256':hashlib.sha256(source_bytes).hexdigest(),
               'publication_enabled':False, 'paid_generation_enabled':False,
               'provider_validated':False}
    if job['operation'] == 'onboarding-check':
        receipt['onboarding_status'] = result['status']
        receipt['configuration_complete'] = result['configuration_complete']
    if job['operation'] == 'listing-draft':
        receipt['draft_status'] = result['status']
        receipt['draft_count'] = len(result['drafts'])
    if job['operation'] == 'offer-contract':
        if any(result.get(flag) is not False for flag in ('dispatch_enabled','production_ready','provider_validated','api_schema_validated')):
            raise ValueError('Invalid offline offer contract result')
        receipt['contract_status'] = result['status']
        receipt['plan_count'] = len(result['plans'])
        receipt['dispatch_enabled'] = False
        receipt['api_schema_validated'] = False
    with receipt_path.open('x',encoding='utf-8') as handle:
        json.dump(receipt,handle,indent=2)
        handle.write('\n')
    return receipt
