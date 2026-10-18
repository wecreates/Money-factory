"""Bound the post-child receipt verifier, including actual named pipes."""
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
from production_test_fixtures import artifact_bodies

spec = importlib.util.spec_from_file_location('output_agent', Path(__file__).with_name('production_agent.py'))
agent = importlib.util.module_from_spec(spec); spec.loader.exec_module(agent)


class ProductionOutputTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.out = self.root/'out'
        self.job = self.root/'job.json'; self.font = self.root/'font.ttf'
        self.job.write_text('{"publication_enabled":false,"paid_generation_enabled":false,"platform":"kdp"}')
        self.font.write_bytes(b'fixture')

    def finish(self, argv, **kwargs):
        (self.out/'package').mkdir(parents=True)
        self.write_package({'art.bin': b'original bytes'})

    def write_package(self, files):
        files = artifact_bodies(overrides=files)
        hashes = {}
        for name, body in files.items():
            (self.out/'package'/name).write_bytes(body)
            hashes[name] = hashlib.sha256(body).hexdigest()
        manifest = {'schema_version': 1, 'platform': 'kdp', 'publication_enabled': False, 'files': hashes}
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        manifest['package_sha256'] = digest
        (self.out/'package/manifest.json').write_text(json.dumps(manifest))
        (self.out/'result.json').write_text(json.dumps({'schema_version': 1, 'platform': 'kdp', 'status': 'REVIEW_REQUIRED',
            'production_ready': False, 'paid_generation_enabled': False,
            'remaining_checks': ['official_template', 'rights', 'editorial', 'independent_visual_review',
                                 'marketplace_account', 'platform_preview', 'release_approval'],
            'publication_enabled': False, 'marketplace_ready': False, 'package_sha256': digest}))

    def run_agent(self, child=None):
        with patch.object(agent, 'run_review_child', side_effect=child or self.finish):
            return agent.run(self.job, self.root, self.font, self.out)

    def reject(self, error, child):
        with self.assertRaisesRegex(ValueError, '^'+error+'$'):
            self.run_agent(child)
        self.assertFalse((self.out/'money-factory-receipt.json').exists())

    def test_result_and_manifest_byte_limits(self):
        for name in ('result.json', 'package/manifest.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                self.out = Path(tmp)/'out'
                def child(argv, **kwargs):
                    self.finish(argv)
                    path = self.out/name
                    path.write_bytes(path.read_bytes()+b' '*2000)
                with patch.object(agent, 'MAX_OUTPUT_JSON_BYTES', 1000, create=True):
                    self.reject('OUTPUT_TOO_LARGE', child)

    def test_artifact_byte_limit(self):
        with patch.object(agent, 'MAX_ARTIFACT_BYTES', 4, create=True):
            self.reject('OUTPUT_TOO_LARGE', self.finish)

    def test_aggregate_limit(self):
        def child(argv, **kwargs):
            self.finish(argv); self.write_package({'one.bin': b'1234', 'two.bin': b'5678'})
        with patch.object(agent, 'MAX_PACKAGE_BYTES', 7, create=True):
            self.reject('PACKAGE_TOO_LARGE', child)

    def test_file_count_limit(self):
        def child(argv, **kwargs):
            self.finish(argv); self.write_package({str(i)+'.bin': b'x' for i in range(33)})
        self.reject('ARTIFACT_BATCH_INVALID', child)

    def test_exact_artifact_and_aggregate_ceiling_and_hash(self):
        with patch.object(agent, 'MAX_ARTIFACT_BYTES', 14, create=True), \
             patch.object(agent, 'MAX_PACKAGE_BYTES', 14, create=True):
            result = self.run_agent()
        self.assertEqual(result['input_sha256'], hashlib.sha256(self.job.read_bytes()).hexdigest())
        self.assertTrue((self.out/'money-factory-receipt.json').is_file())

    def test_wrong_hash_never_writes_receipt(self):
        def child(argv, **kwargs):
            self.finish(argv); (self.out/'package/art.bin').write_bytes(b'tampered')
        self.reject('ARTIFACT_HASH_MISMATCH', child)

    def test_growth_after_stat_still_obeys_byte_limit(self):
        def child(argv, **kwargs): self.finish(argv)
        real_fstat = agent.os.fstat
        def stale_stat(fd):
            info = real_fstat(fd)
            values = list(info); values[6] = 0
            return os.stat_result(values)
        with patch.object(agent, 'MAX_ARTIFACT_BYTES', 4, create=True), \
             patch.object(agent.os, 'fstat', side_effect=stale_stat):
            self.reject('OUTPUT_TOO_LARGE', child)

    def test_invalid_utf8_output_is_rejected(self):
        def child(argv, **kwargs):
            self.finish(argv)
            (self.out/'result.json').write_bytes(b'{"bad":"\xff"}')
        with self.assertRaises(UnicodeError): self.run_agent(child)
        self.assertFalse((self.out/'money-factory-receipt.json').exists())

    def test_fifo_output_rejected_without_writer(self):
        # Run outside this process so the old blocking read fails within 2s.
        for name in ('result.json', 'package/manifest.json', 'package/art.bin', 'money-factory-receipt.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                self.out = Path(tmp)/'out'
                self.finish(None)
                target = self.out/name; target.unlink(missing_ok=True); os.mkfifo(target)
                code = """import importlib.util,sys
from unittest.mock import patch
from pathlib import Path
s=importlib.util.spec_from_file_location('agent',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
original=Path.exists
def exists(p): return False if str(p)==sys.argv[5] else original(p)
with patch.object(m,'run_review_child'),patch.object(Path,'exists',exists):
 try:m.run(sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5])
 except FileExistsError:assert Path(sys.argv[6]).name=='money-factory-receipt.json'
 except ValueError as e:assert str(e)=='OUTPUT_FILE_INVALID',str(e)
 else:raise AssertionError('FIFO accepted')
"""
                result = subprocess.run([sys.executable, '-c', code, str(Path(agent.__file__).resolve()),
                    str(self.job), str(self.root), str(self.font), str(self.out), str(target)],
                    capture_output=True, text=True, timeout=2)
                self.assertEqual(result.returncode, 0, result.stderr)
                if name == 'money-factory-receipt.json':
                    self.assertTrue(target.is_fifo())
                else:
                    self.assertFalse((self.out/'money-factory-receipt.json').exists())


if __name__ == '__main__': unittest.main()
