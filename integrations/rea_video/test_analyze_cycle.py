"""Synthetic identity packets test adapter behavior; actual model smoke is separate."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from integrations.content_control import test_cycle_review as review_fixture
from integrations.content_control.review_package import digest
from integrations.rea_video import analyze_cycle as analyzer


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.packet=review_fixture.ReviewTests();self.packet.setUp();self.base=self.packet.base;self.root=self.packet.root
        self.model_dir=self.base/'models';self.model_dir.mkdir();(self.model_dir/analyzer.MODEL).write_bytes(b'SYNTHETIC_MODEL')
        self.model_patch=patch.object(analyzer,'MODEL_SHA',digest(self.model_dir/analyzer.MODEL));self.model_patch.start()
        self.env_patch=patch.dict('os.environ',{'REA_VIDEO_MODELS':str(self.model_dir),'PUBLICATION_ENABLED':'false','PAID_GENERATION_ENABLED':'false'});self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop();self.model_patch.stop();self.packet.tearDown()

    def fake_run(self,command,*,log,deadline,env,cwd):
        self.assertNotIn('OPENAI_API_KEY',env);self.assertEqual(env['HF_HUB_OFFLINE'],'1')
        mode,report,video,out=command[-4:];identity={'source_commit':analyzer.PIN,'source_files_sha256':{'rea_video/cli.py':'a'*64}}
        if mode=='analyze':
            identity['ocr_runtime_initialized']=True;out=Path(out);out.mkdir()
            (out/'VIDEO.md').write_text('Synthetic diagnostic fixture')
            (out/'storyboard.jpg').write_bytes(b'SYNTHETIC_JPEG')
            data={'analysis':{'ocr':True,'vlm':{'used':False,'requested':False}},'shots':[{'start':0}],
                  'source':{'duration':1},'stems':{},'speech':{},'speakers':{}}
            (out/'breakdown.json').write_text(json.dumps(data))
        Path(report).write_text(json.dumps(identity));log.write_text('synthetic fixture')

    def call(self,output=None):
        return analyzer.analyze_cycle(self.root,output or self.base/'analysis',runtime=sys.executable,timeout=60)

    def test_exact_completed_cycle_binding_and_no_approval(self):
        with patch.object(analyzer,'_run',side_effect=self.fake_run):result=self.call()
        self.assertEqual(result['status'],'DIAGNOSTIC_COMPLETE',result)
        self.assertEqual(result['candidate_sha256'],self.packet.candidate)
        self.assertEqual(result['cycle_files_sha256']['cycle.json'],digest(self.root/'cycle.json'))
        self.assertFalse(result['full_av_review']);self.assertFalse(result['production_approved'])
        self.assertFalse(result['publication_enabled']);self.assertIn('VIDEO.md',result['diagnostics_files_sha256'])

    def test_tampered_cycle_rejected_before_launch(self):
        (self.root/'delivery/video.mp4').write_bytes(b'TAMPERED')
        with patch.object(analyzer,'_run') as run:
            with self.assertRaises(ValueError):self.call()
            run.assert_not_called()

    def test_symlink_and_overlapping_outputs_rejected(self):
        link=self.base/'linked';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):analyzer.analyze_cycle(link,self.base/'other',runtime=sys.executable)
        for output in [self.root/'inside',self.base,self.base/'linked'/'child']:
            with self.assertRaises(ValueError):self.call(output)

    def test_cycle_mutation_during_analysis_blocks_result(self):
        def mutated(*args,**kwargs):
            self.fake_run(*args,**kwargs)
            if args[0][-4]=='analyze':(self.root/'brief.json').write_text('{}')
        with patch.object(analyzer,'_run',side_effect=mutated):result=self.call()
        self.assertEqual(result['status'],'BLOCKED');self.assertNotIn('diagnostics_files_sha256',result)

    def test_failure_retains_blocked_receipt(self):
        with patch.object(analyzer,'_run',side_effect=RuntimeError('pin mismatch fixture')):result=self.call()
        self.assertEqual(result['status'],'BLOCKED');self.assertIn('pin mismatch',result['reason'])
        self.assertEqual(json.loads((self.base/'analysis/analysis.json').read_text())['status'],'BLOCKED')

    def test_missing_cached_model_prevents_launch_and_download(self):
        (self.model_dir/analyzer.MODEL).unlink()
        with patch.object(analyzer,'_run') as run:
            with self.assertRaisesRegex(ValueError,'downloads disabled'):self.call()
            run.assert_not_called()

    def test_invalid_deadline_and_paid_flag_rejected(self):
        for value in (True,0,float('nan'),1801):
            with self.assertRaises(ValueError):analyzer.analyze_cycle(self.root,self.base/'analysis',runtime=sys.executable,timeout=value)
        with patch.dict('os.environ',{'PAID_GENERATION_ENABLED':'true'}):
            with self.assertRaises(ValueError):self.call()

    def test_bounded_log_capture_and_real_guardian_timeout(self):
        log=self.base/'tail.log'
        analyzer._run([sys.executable,'-c','print("x"*200000)'],log=log,deadline=time.monotonic()+10,env={},cwd=self.base)
        self.assertEqual(log.stat().st_size,analyzer.LOG_LIMIT)
        with self.assertRaises(ValueError):
            analyzer._run([sys.executable,'-c','import time;time.sleep(30)'],log=log,deadline=time.monotonic()+.2,env={},cwd=self.base)

    def test_output_symlink_is_not_certified(self):
        def linked(*args,**kwargs):
            self.fake_run(*args,**kwargs)
            if args[0][-4]=='analyze':
                d=Path(args[0][-1]);(d/'leak').symlink_to(self.root/'brief.json')
        with patch.object(analyzer,'_run',side_effect=linked):result=self.call()
        self.assertEqual(result['status'],'BLOCKED')


if __name__=='__main__':unittest.main()
