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

module = importlib.util.spec_from_file_location('pod_agent_snapshot', Path(__file__).with_name('production_agent.py'))
agent = importlib.util.module_from_spec(module); module.loader.exec_module(agent)


class ProductionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root/'job.json'; self.font = self.root/'font.ttf'
        self.font.write_bytes(b'fixture font')
        self.output = self.root/'out'
        self.body = b'{"publication_enabled":false,"paid_generation_enabled":false,"platform":"kdp","title":"Original"}\n'
        self.job.write_bytes(self.body)

    def run_agent(self): return agent.run(self.job, self.root, self.font, self.output)

    def finish(self, argv, **kwargs):
        # A synthetic child isolates input binding; the existing real Node/Python
        # integration test independently checks genuine rendering and manifests.
        root = Path(argv[4]); (root/'package').mkdir(parents=True)
        (root/'package/art.bin').write_bytes(b'fixture')
        manifest = {'schema_version':1,'platform':'kdp','publication_enabled':False,
                    'files':{'art.bin':hashlib.sha256(b'fixture').hexdigest()}}
        manifest['package_sha256'] = hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        (root/'package/manifest.json').write_text(json.dumps(manifest))
        (root/'result.json').write_text(json.dumps({'schema_version':1,'platform':'kdp','status':'REVIEW_REQUIRED','publication_enabled':False,
            'production_ready':False,'paid_generation_enabled':False,
            'remaining_checks':['official_template','rights','editorial','independent_visual_review',
                                'marketplace_account','platform_preview','release_approval'],
            'marketplace_ready':False,'package_sha256':manifest['package_sha256']}))

    def test_mutation_cannot_change_executed_input_or_receipt(self):
        captured = []
        def child(argv, **kwargs):
            self.job.write_text('{"publication_enabled":true,"title":"Changed"}')
            path = Path(argv[2]); captured.append(path)
            self.assertEqual(path.read_bytes(), self.body)
            self.assertNotEqual(path, self.job)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.finish(argv, **kwargs)
        with patch.object(agent.subprocess, 'run', side_effect=child): result = self.run_agent()
        self.assertEqual(result['input_sha256'], hashlib.sha256(self.body).hexdigest())
        self.assertFalse(captured[0].parent.exists())

    def test_source_deleted_after_render_does_not_break_valid_receipt(self):
        def child(argv, **kwargs):
            self.finish(argv, **kwargs); self.job.unlink()
        with patch.object(agent.subprocess, 'run', side_effect=child): result = self.run_agent()
        self.assertEqual(result['input_sha256'], hashlib.sha256(self.body).hexdigest())

    def test_child_failure_removes_only_private_snapshot(self):
        captured = []
        def child(argv, **kwargs):
            path = Path(argv[2]); captured.append(path)
            raise subprocess.CalledProcessError(1, argv)
        with patch.object(agent.subprocess, 'run', side_effect=child):
            with self.assertRaises(subprocess.CalledProcessError): self.run_agent()
        self.assertEqual(self.job.read_bytes(), self.body)
        self.assertFalse(captured[0].parent.exists())

    def test_job_ceiling_checked_before_child(self):
        self.job.write_bytes(self.body+b' '*100)
        with patch.object(agent, 'MAX_JOB_BYTES', len(self.body), create=True), \
             patch.object(agent.subprocess, 'run', side_effect=AssertionError('child reached')):
            with self.assertRaisesRegex(ValueError, '^JOB_TOO_LARGE$'): self.run_agent()
        self.assertFalse(self.output.exists())

    def test_exact_ceiling_and_utf8_bytes_preserved(self):
        self.body = self.body.replace(b'Original', 'Étoile 日本語'.encode())
        self.job.write_bytes(self.body)
        def child(argv, **kwargs):
            self.assertEqual(Path(argv[2]).read_bytes(),self.body); self.finish(argv, **kwargs)
        with patch.object(agent, 'MAX_JOB_BYTES', len(self.body), create=True), \
             patch.object(agent.subprocess, 'run', side_effect=child): result = self.run_agent()
        self.assertEqual(result['input_sha256'],hashlib.sha256(self.body).hexdigest())

    def test_invalid_utf8_and_nonobject_job_never_execute(self):
        for body in (b'{"publication_enabled":false,"paid_generation_enabled":false,"x":"\xff"}',b'[]',b'null'):
            self.job.write_bytes(body)
            with patch.object(agent.subprocess, 'run', side_effect=AssertionError('child reached')):
                with self.assertRaises((ValueError,UnicodeError)): self.run_agent()

    def test_fifo_rejected_without_waiting_for_writer(self):
        self.job.unlink(); os.mkfifo(self.job)
        code = ("import importlib.util,sys\n"
                "s=importlib.util.spec_from_file_location('agent',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
                "try:m.run(sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5])\n"
                "except ValueError as e:assert str(e)=='JOB_FILE_INVALID'\n"
                "else:raise AssertionError('FIFO accepted')\n")
        result = subprocess.run([sys.executable,'-c',code,str(Path(agent.__file__).resolve()),
            str(self.job),str(self.root),str(self.font),str(self.output)],capture_output=True,text=True,timeout=2)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__': unittest.main()
