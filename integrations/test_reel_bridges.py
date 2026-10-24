import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reel_bridges import BRIDGES, handles, run_bridge

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / 'integrations/repositories.json').read_text())
spec = importlib.util.spec_from_file_location('candidate_worker', ROOT / 'integrations/run.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class BridgeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def job(self, tool='open-seo', operation='readiness'):
        return {'tool': tool, 'operation': operation, 'output': str(self.root / f'{tool}-{operation}.json'),
                'publication_enabled': False, 'paid_generation_enabled': False}

    def test_registry_has_exact_pins_and_allowlist(self):
        self.assertEqual(len(REGISTRY['external_bridges']), len(BRIDGES))
        self.assertEqual({e['id'] for e in REGISTRY['external_bridges']}, set(BRIDGES))
        for entry in REGISTRY['external_bridges']:
            config = BRIDGES[entry['id']]
            self.assertEqual(entry['revision'], config[1])
            self.assertEqual(entry['operations'], list(config[2]))
            self.assertFalse(entry['live_execution_enabled'])
            self.assertFalse(entry['production_ready'])
            self.assertFalse(entry['enabled'])

    def test_foreign_regular_package_cannot_shadow_owned_adapter(self):
        shadow = self.root/'shadow'/'open_seo'; shadow.mkdir(parents=True)
        (shadow/'__init__.py').write_text('')
        (shadow/'adapter.py').write_text('raise RuntimeError("FOREIGN_ADAPTER_LOADED")\n')
        job = self.job(); path = self.root/'job.json'; path.write_text(json.dumps(job))
        completed = subprocess.run([sys.executable, str(ROOT/'integrations/run.py'), str(path),
                                    '--runtime', str(self.root/'runtime')],
                                   env=dict(os.environ, PYTHONPATH=str(shadow.parent)),
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(Path(job['output']).read_text())
        self.assertEqual(value['tool'], 'open-seo')
        self.assertEqual(value['runtime_status'], 'OFFLINE_BRIDGE_ONLY')

    def test_actual_readiness_uses_existing_runner_and_writes_bound_receipt(self):
        for tool, config in BRIDGES.items():
            operation = 'readiness' if 'readiness' in config[2] else 'status'
            with self.subTest(tool=tool), patch.object(worker, 'source', side_effect=AssertionError('Upstream must not execute')):
                job = self.job(tool, operation)
                receipt = worker.run(job, self.root / 'runtime')
                output = Path(job['output'])
                value = json.loads(output.read_text())
                self.assertEqual(receipt['status'], value['status'])
                self.assertEqual(receipt['output_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
                self.assertEqual(receipt['revision'], config[1])
                self.assertEqual(receipt['execution_kind'], 'project_owned_offline_adapter')
                self.assertFalse(receipt['upstream_runtime_verified'])
                self.assertFalse(receipt['production_ready'])
                self.assertEqual(json.loads(Path(str(output)+'.receipt.json').read_text()), receipt)

    def test_existing_voicestudio_pin_and_synthesis_route_are_preserved(self):
        voice = next(e for e in REGISTRY['media_tools'] if e['id'] == 'voicestudio')
        self.assertEqual(voice['revision'], '4df5033e5a1a92e22936fb4d7d2d39e03cf10a91')
        self.assertFalse(handles({'tool': 'voicestudio', 'operation': 'synthesize'}))
        with patch.object(worker, 'source', side_effect=RuntimeError('LEGACY_SOURCE_PATH')):
            with self.assertRaisesRegex(RuntimeError, 'LEGACY_SOURCE_PATH'):
                worker.run(self.job('voicestudio', 'synthesize'), self.root / 'runtime')

    def test_unknown_operations_never_bypass_upstream_gate(self):
        for tool in BRIDGES:
            self.assertFalse(handles({'tool': tool, 'operation': 'install'}))
            with self.assertRaises(ValueError): run_bridge(self.job(tool, 'install'), REGISTRY)

    def test_registry_pin_or_operation_drift_blocks(self):
        for key, value in [('revision', '0'*40), ('operations', ['readiness'])]:
            registry = copy.deepcopy(REGISTRY)
            next(e for e in registry['external_bridges'] if e['id']=='open-seo')[key] = value
            with self.assertRaises(ValueError): run_bridge(self.job(), registry)

    def test_flags_fail_closed(self):
        for key, value in [('publication_enabled', True), ('paid_generation_enabled', 0),
                           ('paid_services_enabled', True), ('network_enabled', True)]:
            job = self.job(); job[key] = value
            with self.assertRaises(ValueError): run_bridge(job, REGISTRY)

    def test_explicit_offline_disable_is_respected(self):
        registry = copy.deepcopy(REGISTRY)
        next(e for e in registry['external_bridges'] if e['id']=='open-seo')['offline_bridge_enabled'] = False
        with self.assertRaisesRegex(ValueError, 'disabled'): run_bridge(self.job(), registry)

    def test_outputs_never_overwrite_or_follow_dangling_symlinks(self):
        job = self.job(); output = Path(job['output'])
        output.write_text('keep')
        with self.assertRaises(ValueError): run_bridge(job, REGISTRY)
        self.assertEqual(output.read_text(), 'keep')
        output.unlink(); output.symlink_to(self.root/'absent')
        with self.assertRaises(ValueError): run_bridge(job, REGISTRY)
        self.assertFalse((self.root/'absent').exists())

    def test_output_parent_symlinks_and_parent_traversal_rejected(self):
        actual = self.root/'actual'; actual.mkdir()
        linked = self.root/'linked'; linked.symlink_to(actual, target_is_directory=True)
        for output in (linked/'status.json', actual/'..'/'actual'/'status.json'):
            job = self.job(); job['output'] = str(output)
            with self.assertRaises((OSError, ValueError)): run_bridge(job, REGISTRY)
        self.assertEqual(list(actual.iterdir()), [])

    def test_blocked_import_has_blocked_receipt(self):
        path = self.root/'input.json'
        path.write_text(json.dumps({'results':[{'keyword':'test','ok':False,'error':'Not available'}]}))
        job = self.job(operation='import-serp'); job['input'] = str(path)
        receipt = worker.run(job, self.root/'runtime')
        self.assertEqual(receipt['status'], 'BLOCKED')


if __name__ == '__main__': unittest.main()
