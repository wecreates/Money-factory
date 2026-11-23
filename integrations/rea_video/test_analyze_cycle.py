"""Synthetic identity packets test adapter behavior; actual model smoke is separate."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import zipfile

from integrations.content_control import test_cycle_review as review_fixture
from integrations.content_control.review_package import digest
from integrations.rea_video import analyze_cycle as analyzer


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.packet=review_fixture.ReviewTests();self.packet.setUp();self.base=self.packet.base;self.root=self.packet.root
        self.model_dir=self.base/'models';self.model_dir.mkdir();(self.model_dir/analyzer.MODEL).write_bytes(b'SYNTHETIC_MODEL')
        self.model_patch=patch.object(analyzer,'MODEL_SHA',digest(self.model_dir/analyzer.MODEL));self.model_patch.start()
        self.env_patch=patch.dict('os.environ',{'REA_VIDEO_MODELS':str(self.model_dir),'PUBLICATION_ENABLED':'false','PAID_GENERATION_ENABLED':'false'});self.env_patch.start()
        self.detected_starts = [0]

    def tearDown(self):
        self.env_patch.stop();self.model_patch.stop();self.packet.tearDown()

    def fake_run(self,command,*,log,deadline,env,cwd):
        self.assertNotIn('OPENAI_API_KEY',env);self.assertEqual(env['HF_HUB_OFFLINE'],'1')
        mode,report,video,out=command[-4:];identity={'source_commit':analyzer.PIN,'source_files_sha256':{'rea_video/cli.py':'a'*64}}
        if mode=='analyze':
            identity['ocr_runtime_initialized']=True;out=Path(out);out.mkdir()
            (out/'VIDEO.md').write_text('Synthetic diagnostic fixture')
            (out/'storyboard.jpg').write_bytes(b'SYNTHETIC_JPEG')
            data={'analysis':{'ocr':True,'vlm':{'used':False,'requested':False}},
                  'shots':[{'start': start} for start in self.detected_starts],
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
        self.assertEqual(result['summary']['authored_cut_coverage']['status'], 'UNAVAILABLE')

    def add_render_scene_starts(self):
        delivery = self.root/'delivery'
        render_receipt = delivery/'render.json'
        render = json.loads(render_receipt.read_text())
        render['scenes'] = [{'scene_id': 's1', 'start': 0}, {'scene_id': 's2', 'start': .625}]
        review_fixture.write(render_receipt, render)
        (self.root/'render/render.json').write_bytes(render_receipt.read_bytes())
        package = json.loads((delivery/'package.json').read_text())
        package['render_receipt_sha256'] = package['files_sha256']['render.json'] = digest(render_receipt)
        review_fixture.write(delivery/'package.json', package)
        cycle = json.loads((self.root/'cycle.json').read_text())
        cycle['package_sha256'] = digest(delivery/'package.json')
        review_fixture.write(self.root/'cycle.json', cycle)
        with zipfile.ZipFile(delivery/'review-package.zip', 'w') as archive:
            for member in (*package['files_sha256'], 'package.json'):
                archive.write(delivery/member, member)

    def test_reports_missing_authored_cut_and_retains_bound_samples(self):
        self.add_render_scene_starts()
        self.detected_starts = [0, .125]
        snapshot = analyzer.inspect_cycle(self.root)
        def sampler(root, target, *, timeout):
            self.assertEqual(root, self.root)
            self.assertTrue(10 <= timeout < 60)
            target.mkdir()
            receipt = {'status': 'SCENE_SAMPLES_READY', 'candidate_sha256': snapshot['candidate_sha256'],
                       'source_files_sha256': snapshot['files_sha256'], 'sampled_scene_count': 2}
            review_fixture.write(target/'scene-review.json', receipt)
            return receipt
        with patch.object(analyzer, '_run', side_effect=self.fake_run), patch(
            'integrations.content_control.cycle_scene_review.make_scene_review', side_effect=sampler
        ):
            result = self.call()
        self.assertEqual(result['status'], 'DIAGNOSTIC_COMPLETE', result)
        coverage = result['summary']['authored_cut_coverage']
        self.assertEqual(coverage['status'], 'MISSING_AUTHORED_CUTS')
        self.assertEqual(coverage['missing_cuts'], [{'scene_id': 's2', 'authored_seconds': .625}])
        self.assertEqual(coverage['unmatched_detected_seconds'], [.125])
        self.assertEqual(coverage['matched_cuts'], [])
        retained = result['authored_scene_samples']
        self.assertEqual(retained['status'], 'SCENE_SAMPLES_READY')
        self.assertEqual(retained['receipt_sha256'], digest(self.base/'analysis'/retained['receipt']))
        self.assertFalse(result['full_av_review'])

    def test_blocked_sampler_retains_successful_detector_diagnostics(self):
        self.add_render_scene_starts()
        with patch.object(analyzer, '_run', side_effect=self.fake_run), patch(
            'integrations.content_control.cycle_scene_review.make_scene_review',
            side_effect=ValueError('Frame unavailable')
        ):
            result = self.call()
        self.assertEqual(result['status'], 'PARTIAL_DIAGNOSTIC')
        self.assertEqual(result['summary']['authored_cut_coverage']['status'], 'MISSING_AUTHORED_CUTS')
        self.assertIn('breakdown.json', result['diagnostics_files_sha256'])
        self.assertEqual(result['authored_scene_samples'], {'status': 'BLOCKED', 'reason': 'Frame unavailable'})

    def test_sampler_cannot_run_with_insufficient_time(self):
        with patch('integrations.content_control.cycle_scene_review.make_scene_review') as sampler:
            result = analyzer._authored_samples(self.root, self.base, {}, {'status': 'MISSING_AUTHORED_CUTS'},
                                                time.monotonic()+5)
        self.assertEqual(result['status'], 'BLOCKED')
        sampler.assert_not_called()

    def test_nearby_detections_match_once_at_most(self):
        rows = [{'scene_id': id_, 'start': time} for id_, time in (('s1', 0), ('s2', .625), ('s3', .75))]
        summary = {'duration_seconds': 1, 'detected_boundaries_seconds': [0, .125, .75, .9375]}
        result = analyzer._cut_coverage({'scenes': rows}, [{'id': row['scene_id']} for row in rows], summary)
        self.assertEqual(result['matched_cuts'], [{'scene_id': 's2', 'authored_seconds': .625, 'detected_seconds': .75}])
        self.assertEqual(result['missing_cuts'], [{'scene_id': 's3', 'authored_seconds': .75}])
        self.assertEqual(result['unmatched_detected_seconds'], [.125, .9375])

    def test_invalid_detected_start_blocks_diagnostic(self):
        for i, value in enumerate(([0, True], [0, .625, .25], [0, .625, .625], [0, 1])):
            self.detected_starts = value
            with patch.object(analyzer,'_run',side_effect=self.fake_run):
                result = self.call(self.base / f'invalid-{i}')
            self.assertEqual(result['status'], 'BLOCKED', result)
            self.assertIn('Invalid detected shot starts', result['reason'])

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
