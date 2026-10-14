"""Integration boundary tests; these do not claim real upstream execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import run
import hosted_job


class REAWiringTests(unittest.TestCase):
    def test_registry_keeps_original_seven_and_adds_engineering_pin(self):
        self.assertEqual([e['order'] for e in run.REGISTRY['repositories']], list(range(1, 8)))
        self.assertEqual(run.TOOLS['rea']['revision'], 'npm:rea-agents@6.4.0')
        self.assertTrue((run.source('rea') / 'package-lock.json').is_file())

    def test_npm_pin_rejects_changed_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'integrations/rea'
            target.mkdir(parents=True)
            for name in ('package.json', 'package-lock.json'):
                (target / name).write_bytes((run.ROOT / 'integrations/rea' / name).read_bytes())
            lock = json.loads((target / 'package-lock.json').read_text())
            lock['packages']['node_modules/rea-agents']['version'] = '6.3.0'
            (target / 'package-lock.json').write_text(json.dumps(lock))
            with patch.object(run, 'ROOT', root), self.assertRaisesRegex(ValueError, 'npm source pin'):
                run.source('rea')

    def test_directories_only_for_reviewed_rea_operations_and_no_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / 'integrations/jobs'
            fixture = jobs / 'fixture'
            fixture.mkdir(parents=True)
            (fixture / 'index.js').write_text('export const answer = 42;')
            base = dict(tool='rea', operation='analyze-javascript-application', input='fixture',
                        publication_enabled=False, paid_generation_enabled=False)
            for operation in ('analyze-javascript-application', 'mcp-smoke', 'inspect-local-web-page'):
                (jobs / 'rea.job.json').write_text(json.dumps(base | {'operation': operation}))
                self.assertEqual(hosted_job.load_job('rea.job.json', root / 'out', root)['input'], str(fixture))
            for change in ({'operation':'inspect-artifact'}, {'operation':'capture-owned-process'}, {'input':'../../'},
                           {'tool':'claude-seo','operation':'parse-html'}, {'input':'/etc'}):
                (jobs / 'rea.job.json').write_text(json.dumps(base | change))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    hosted_job.load_job('rea.job.json', root / 'out', root)
            (jobs / 'outside').symlink_to(root, target_is_directory=True)
            (jobs / 'rea.job.json').write_text(json.dumps(base | {'input':'outside'}))
            with self.assertRaises(ValueError):
                hosted_job.load_job('rea.job.json', root / 'out', root)

    def test_blocked_adapter_never_creates_pass_receipt(self):
        import types
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'result.json'
            adapter = types.ModuleType('rea.adapter')
            adapter.dispatch = lambda job, runtime: {'status':'BLOCKED','reason':'missing dependency'}
            with patch.dict('sys.modules', {'rea.adapter': adapter}):
                result = run.run(dict(tool='rea', operation='mcp-smoke', output=str(output)), root / 'runtime')
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(json.loads(output.read_text())['status'], 'BLOCKED')
            self.assertFalse(Path(str(output)+'.receipt.json').exists())

    def test_hosted_rea_uses_local_runner_not_content_control_bridge(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'out'
            job = dict(tool='rea', operation='mcp-smoke', output=str(output/'result.json'))
            def local_runner(job, runtime):
                result = Path(job['output']); result.write_text('{}')
                receipt = {'status':'PASS','publication_enabled':False,
                           'output_sha256':hashlib.sha256(result.read_bytes()).hexdigest()}
                Path(str(result)+'.receipt.json').write_text(json.dumps(receipt))
                return receipt
            with patch.object(hosted_job, 'run', side_effect=local_runner) as local, \
                    patch.object(hosted_job.subprocess, 'run') as external:
                hosted_job.execute(job, root/'runtime', root/'missing-cc', output)
            local.assert_called_once(); external.assert_not_called()


if __name__ == '__main__': unittest.main()
