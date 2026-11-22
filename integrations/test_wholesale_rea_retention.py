"""Regression for PR522's adjacent REA retention failure; synthetic data only."""
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
import run
from persist_job import LIMIT, read_file


class REARetention(unittest.TestCase):
    def test_large_result_preserves_complete_json_and_receipt_bytes(self):
        # Reuses PR170's whitespace-growth fixture, not the real cloud artifact.
        evidence = {'status': 'PASS', 'evidence': {'rows': [
            {'id': i, 'values': [1, 2, 3], 'note': 'original synthetic fixture'}
            for i in range(10000)]}, 'production_ready': False}
        self.assertGreater(len((json.dumps(evidence, indent=2)+'\n').encode()), LIMIT)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root/'result.json'
            adapter = types.ModuleType('rea.adapter')
            adapter.dispatch = lambda job, runtime: evidence
            with patch.dict('sys.modules', {'rea.adapter': adapter}), \
                 patch.object(run, 'source', return_value=root), \
                 patch.object(run, 'fcntl', Mock(LOCK_EX=2)):
                receipt = run.run(dict(tool='rea', operation='analyze-javascript-application',
                    output=str(output), publication_enabled=False, paid_generation_enabled=False), root/'runtime')
            data = read_file(root, 'result.json')
            self.assertEqual(json.loads(data), evidence)
            self.assertLessEqual(len(data), LIMIT)
            self.assertEqual(receipt['output_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(json.loads(Path(str(output)+'.receipt.json').read_text()), receipt)
            self.assertFalse(receipt['publication_enabled'])

    def test_existing_limit_and_missing_file_guard_remain_enforced(self):
        self.assertEqual(LIMIT, 1048576)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Missing, oversized or linked evidence'):
                read_file(root, 'missing.json')
            (root/'result.json').write_bytes(b'x'*(LIMIT+1))
            with self.assertRaisesRegex(ValueError, 'Missing, oversized or linked evidence'):
                read_file(root, 'result.json')
