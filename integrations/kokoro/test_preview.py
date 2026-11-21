import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from integrations.kokoro import preview


class PreviewTests(unittest.TestCase):
    def test_changed_approved_text_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp)/'contract.json'
            contract.write_text('{"status":"ACTIVE","publication_enabled":false,"narration_text":"Original words."}')
            original = preview.digest(contract)
            contract.write_text(contract.read_text().replace('Original', 'Changed'))
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                preview.read_contract(contract, original)

    def test_mismatched_model_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model/config.json';path.parent.mkdir();path.write_text('unreviewed bytes')
            with self.assertRaisesRegex(ValueError, 'Pinned model'):
                preview.verify_assets(tmp)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);contract=root/'contract.json'
            contract.write_text('{"status":"ACTIVE","publication_enabled":false,"narration_text":"Original words."}')
            output=root/'prior';output.mkdir();marker=output/'keep';marker.write_text('prior result')
            with patch.object(preview,'verify_assets',return_value={'model_revision':'fixture'}), patch.object(preview,'bounded',side_effect=AssertionError('Generation started')):
                with self.assertRaises(FileExistsError):
                    preview.run_preview(root,contract,preview.digest(contract),output,'am_adam')
            self.assertEqual(marker.read_text(),'prior result')

    def test_ppid_memory_scan_counts_children_without_task_children_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for pid,parent,kib in [(10,1,10),(11,10,200),(12,11,300),(13,1,400)]:
                directory=root/str(pid);directory.mkdir();(directory/'status').write_text(f'PPid:\t{parent}\nVmRSS:\t{kib} kB\n')
            self.assertEqual(preview.process_tree_rss(10,root),510*1024)
            self.assertIsNone(preview.process_tree_rss(99,root))

    def test_missing_owned_live_rss_fails_closed_but_zombies_count_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for pid,body in [(10,'PPid: 1\nVmRSS: 10 kB\nState: S (sleeping)\n'),(11,'PPid: 10\nState: S (sleeping)\n')]:
                directory=root/str(pid);directory.mkdir();(directory/'status').write_text(body)
            with self.assertRaisesRegex(RuntimeError,'memory observation unavailable'):
                preview.process_tree_rss(10,root)
            (root/'11/status').write_text('PPid: 10\nState: Z (zombie)\n')
            self.assertEqual(preview.process_tree_rss(10,root),10*1024)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux process bounds')
    def test_deadline_cleans_actual_nested_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'pids.json'
            command=[sys.executable,'-c',f'import os,subprocess,sys,time,json;from pathlib import Path;c=subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"]);Path({str(marker)!r}).write_text(json.dumps([os.getpid(),c.pid]));time.sleep(10)']
            try:
                result=preview.bounded(command,environment={'PATH':os.environ['PATH']},cwd=root,input_bytes=b'',log=root/'log',lease_fd=None,cpus=sorted(os.sched_getaffinity(0))[:2],timeout=.5)
                self.assertNotEqual(result['returncode'],0)
            except RuntimeError as error:
                self.assertIn('bound',str(error))
            pids=json.loads(marker.read_text())
            for pid in pids:
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    try:
                        status=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1][0]
                        if status=='Z':break
                    except (FileNotFoundError,ProcessLookupError):break
                    time.sleep(.02)
                else:
                    os.kill(pid,signal.SIGKILL)
                    self.fail('Owned process survived deadline')

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux process bounds')
    def test_resident_memory_threshold_stops_real_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(RuntimeError,'bound'):
                preview.bounded([sys.executable,'-c','import time;x=bytearray(40*1024*1024);time.sleep(10)'],
                    environment={'PATH':os.environ['PATH']},cwd=root,input_bytes=b'',log=root/'log',lease_fd=None,
                    cpus=sorted(os.sched_getaffinity(0))[:2],timeout=3,rss_limit=20*1024*1024)


if __name__=='__main__':unittest.main()
