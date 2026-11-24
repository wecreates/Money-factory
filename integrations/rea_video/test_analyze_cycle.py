"""Synthetic identity packets test adapter behavior; actual model smoke is separate."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import zipfile

from integrations.content_control import test_cycle_review as review_fixture
from integrations.content_control import cycle_review
from integrations.content_control.cycle_live_comparison import record_live_comparison
from integrations.content_control.cycle_review import record_review, revision_brief
from integrations.content_control.review_package import digest
from integrations.rea_video import analyze_cycle as analyzer


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.packet=review_fixture.ReviewTests();self.packet.setUp();self.base=self.packet.base;self.root=self.packet.root
        self.model_dir=self.base/'models';self.model_dir.mkdir();(self.model_dir/analyzer.MODEL).write_bytes(b'SYNTHETIC_MODEL')
        self.model_patch=patch.object(analyzer,'MODEL_SHA',digest(self.model_dir/analyzer.MODEL));self.model_patch.start()
        self.env_patch=patch.dict('os.environ',{'REA_VIDEO_MODELS':str(self.model_dir),'PUBLICATION_ENABLED':'false','PAID_GENERATION_ENABLED':'false'});self.env_patch.start()
        self.detected_starts = [0]
        self.comparison_index = 0

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

    def record(self, submission, output, **kwargs):
        self.comparison_index += 1
        receipt = self.base / f'rea-comparison-{self.comparison_index}.json'
        record_live_comparison(self.root, self.packet.comparison_source, receipt)
        return record_review(
            self.root, submission, output,
            live_comparison_source=self.packet.comparison_source,
            live_comparison_receipt=receipt, **kwargs)

    def test_exact_completed_cycle_binding_and_no_approval(self):
        with patch.object(analyzer,'_run',side_effect=self.fake_run):result=self.call()
        self.assertEqual(result['status'],'DIAGNOSTIC_COMPLETE',result)
        self.assertEqual(result['candidate_sha256'],self.packet.candidate)
        self.assertEqual(result['cycle_files_sha256']['cycle.json'],digest(self.root/'cycle.json'))
        self.assertFalse(result['full_av_review']);self.assertFalse(result['production_approved'])
        self.assertFalse(result['publication_enabled']);self.assertIn('VIDEO.md',result['diagnostics_files_sha256'])
        self.assertEqual(result['summary']['authored_cut_coverage']['status'], 'UNAVAILABLE')

    def test_review_consumes_exact_diagnostics_without_approving_the_candidate(self):
        with patch.object(analyzer, '_run', side_effect=self.fake_run):
            result = self.call()
        output = self.base/'analysis'
        submission = self.packet.submitted
        review_fixture.write(submission, dict(self.packet.review, reviewed_at=result['finished_at']))
        record = self.record(submission, self.packet.recorded,
                             rea_analysis=output/'analysis.json')
        evidence = record['rea_diagnostics']
        self.assertEqual(evidence['receipt_sha256'], digest(output/'analysis.json'))
        self.assertEqual(evidence['detected_segments'], 1)
        self.assertEqual(evidence['diagnostic_artifact_count'], 3)
        self.assertEqual(evidence['authored_cut_coverage']['status'], 'UNAVAILABLE')
        self.assertFalse(evidence['runtime_execution_independently_verified'])
        for name in ('independent_verification', 'full_av_review', 'production_approved', 'publication_enabled'):
            self.assertIs(record[name], False)

    def test_review_rejects_stale_altered_or_blocked_diagnostics(self):
        with patch.object(analyzer, '_run', side_effect=self.fake_run):
            result = self.call()
        output = self.base/'analysis'
        receipt = output/'analysis.json'
        original = receipt.read_bytes()
        submission = self.packet.submitted
        record = self.packet.recorded
        review_fixture.write(submission, dict(self.packet.review, reviewed_at=result['finished_at']))
        for changed, error in (
            ({'candidate_sha256': '0' * 64}, 'do not bind the reviewed cycle'),
            ({'status': 'BLOCKED'}, 'Usable pinned'),
            ({'finished_at': '2026-01-02T00:00:00Z'}, 'must follow the cycle'),
            ({'finished_at': '2099-01-02T00:00:00Z'}, 'future evidence forbidden'),
            ({'summary': dict(result['summary'], detected_segments=999)}, 'summary does not match'),
        ):
            with self.subTest(changed=changed):
                review_fixture.write(receipt, dict(result, **changed))
                with self.assertRaisesRegex(ValueError, error):
                    self.record(submission, record, rea_analysis=receipt)
                self.assertFalse(record.exists())
        receipt.write_bytes(original)
        review_fixture.write(submission, self.packet.review)
        with self.assertRaisesRegex(ValueError, 'precede the review'):
            self.record(submission, record, rea_analysis=receipt)
        review_fixture.write(submission, dict(self.packet.review, reviewed_at=result['finished_at']))
        with self.assertRaisesRegex(ValueError, 'separate from the REA'):
            self.record(submission, output/'diagnostics/new.json', rea_analysis=receipt)
        (output/'diagnostics/VIDEO.md').write_text('Altered')
        with self.assertRaisesRegex(ValueError, 'artifact identity mismatch'):
            self.record(submission, record, rea_analysis=receipt)
        self.assertFalse(record.exists())

    def test_review_rejects_diagnostics_changed_while_summarizing(self):
        with patch.object(analyzer, '_run', side_effect=self.fake_run):
            result = self.call()
        submission = self.packet.submitted
        review_fixture.write(submission, dict(self.packet.review, reviewed_at=result['finished_at']))
        summarize = analyzer._summarize

        def summarize_then_change(directory):
            summary = summarize(directory)
            (directory/'VIDEO.md').write_text('Changed after first manifest check')
            return summary

        with patch.object(analyzer, '_summarize', side_effect=summarize_then_change), \
             self.assertRaisesRegex(ValueError, 'artifacts changed while recording'):
            self.record(submission, self.packet.recorded,
                        rea_analysis=self.base/'analysis/analysis.json')
        self.assertFalse(self.packet.recorded.exists())

    def test_review_rejects_diagnostics_changed_during_final_cycle_check(self):
        with patch.object(analyzer, '_run', side_effect=self.fake_run):
            result = self.call()
        submission = self.packet.submitted
        review_fixture.write(submission, dict(self.packet.review, reviewed_at=result['finished_at']))
        inspect = cycle_review.inspect_cycle
        checks = 0

        def inspect_then_change(root):
            nonlocal checks
            checks += 1
            snapshot = inspect(root)
            if checks == 2:
                (self.base/'analysis/diagnostics/VIDEO.md').write_text('Changed during final cycle check')
            return snapshot

        with patch.object(cycle_review, 'inspect_cycle', side_effect=inspect_then_change), \
             self.assertRaisesRegex(ValueError, 'artifacts changed while recording'):
            self.record(submission, self.packet.recorded,
                        rea_analysis=self.base/'analysis/analysis.json')
        self.assertEqual(checks, 2)
        self.assertFalse(self.packet.recorded.exists())

    def add_render_scene_starts(self):
        delivery = self.root/'delivery'
        render_receipt = delivery/'render.json'
        render = json.loads(render_receipt.read_text())
        render['scenes'] = [
            {'scene_id': 's1', 'start': 0, 'end': .625},
            {'scene_id': 's2', 'start': .625, 'end': 1},
        ]
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

    def ready_sampler(self, root, target, *, timeout):
        from integrations.content_control import cycle_scene_review

        snapshot = analyzer.inspect_cycle(self.root)
        target.mkdir()
        for name, body in {
            'scene-01.png': b'FRAME_ONE', 'scene-02.png': b'FRAME_TWO',
            'contact-sheet.jpg': b'CONTACT', 'index.html': b'<html>bound gallery</html>',
        }.items():
            (target/name).write_bytes(body)
        artifacts = {path.name: digest(path) for path in target.iterdir()}
        receipt = {
            'schema_version': 1, 'status': 'SCENE_SAMPLES_READY',
            'candidate_sha256': snapshot['candidate_sha256'],
            'source_files_sha256': snapshot['files_sha256'],
            'sampled_scene_count': 2, 'tool_sha256': digest(cycle_scene_review.__file__),
            'finished_at': '2026-01-03T01:00:00+00:00',
            'artifacts_sha256': artifacts,
            'media': {'duration_seconds': 1},
            'timing_source': 'delivery/render.json scenes (measured renderer timeline)',
            'planned_storyboard_times_used': False,
            'scope': cycle_scene_review.SCOPE,
            'scenes': [
                {'scene_number': 1, 'scene_id': 's1', 'start_seconds': 0,
                 'end_seconds': .625, 'requested_sample_seconds': .3125,
                 'decoded_frame_pts_seconds': .333333,
                 'frame': 'scene-01.png', 'frame_sha256': artifacts['scene-01.png']},
                {'scene_number': 2, 'scene_id': 's2', 'start_seconds': .625,
                 'end_seconds': 1, 'requested_sample_seconds': .8125,
                 'decoded_frame_pts_seconds': .833333,
                 'frame': 'scene-02.png', 'frame_sha256': artifacts['scene-02.png']},
            ],
            **dict.fromkeys(('publication_enabled', 'paid_generation_enabled',
                'production_approved', 'production_ready', 'full_av_review',
                'listening_verified', 'independent_creative_verification'), False),
        }
        review_fixture.write(target/'scene-review.json', receipt)
        return receipt

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

    def test_review_consumes_exact_authored_gallery_and_feeds_revision_actions(self):
        self.add_render_scene_starts()
        self.detected_starts = [0, .125]
        with patch.object(analyzer, '_run', side_effect=self.fake_run), patch(
            'integrations.content_control.cycle_scene_review.make_scene_review',
            side_effect=self.ready_sampler
        ):
            result = self.call()
        review_fixture.write(self.packet.submitted,
                             dict(self.packet.review, reviewed_at=result['finished_at']))
        recorded = self.record(self.packet.submitted, self.packet.recorded,
                               rea_analysis=self.base/'analysis/analysis.json')
        self.assertEqual(recorded['status'], 'REVISION_REQUIRED')
        self.assertEqual(recorded['rea_diagnostics']['authored_scene_samples']['status'],
                         'SCENE_SAMPLES_READY')
        self.assertEqual(recorded['rea_diagnostics']['authored_scene_samples']['artifact_count'], 4)
        self.assertEqual(recorded['diagnostic_findings'][0]['scene_id'], 's2')
        self.assertIn('human audiovisual judgment', recorded['diagnostic_findings'][0]['action'])
        self.assertFalse(recorded['full_av_review'])

        updated = review_fixture.brief()
        updated['scenes'][1]['narration'] = 'My wallet requests another review.'
        handoff = revision_brief(self.root, self.packet.recorded, updated,
                                 self.base/'diagnostic-revision')
        self.assertEqual(handoff['review_diagnostic_findings'], recorded['diagnostic_findings'])
        self.assertEqual(handoff['rea_diagnostics_receipt_sha256'],
                         recorded['rea_diagnostics']['receipt_sha256'])
        self.assertFalse(handoff['feedback_resolution_verified'])

    def test_authored_gallery_tamper_and_removed_diagnostic_action_fail_closed(self):
        self.add_render_scene_starts()
        self.detected_starts = [0, .125]
        with patch.object(analyzer, '_run', side_effect=self.fake_run), patch(
            'integrations.content_control.cycle_scene_review.make_scene_review',
            side_effect=self.ready_sampler
        ):
            result = self.call()
        review_fixture.write(self.packet.submitted,
                             dict(self.packet.review, reviewed_at=result['finished_at']))
        gallery = self.base/'analysis/authored-scenes/index.html'
        original = gallery.read_bytes(); gallery.write_bytes(b'TAMPERED')
        with self.assertRaisesRegex(ValueError, 'artifact identity mismatch'):
            self.record(self.packet.submitted, self.packet.recorded,
                        rea_analysis=self.base/'analysis/analysis.json')
        self.assertFalse(self.packet.recorded.exists())
        gallery.write_bytes(original)
        self.record(self.packet.submitted, self.packet.recorded,
                    rea_analysis=self.base/'analysis/analysis.json')
        recorded = json.loads(self.packet.recorded.read_text())
        del recorded['diagnostic_findings']
        recorded['feedback'] = [item for item in recorded['feedback']
                                if item.get('source') != 'rea_video_diagnostic']
        review_fixture.write(self.packet.recorded, recorded)
        updated = review_fixture.brief()
        updated['scenes'][1]['narration'] = 'My wallet requests another review.'
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            revision_brief(self.root, self.packet.recorded, updated,
                           self.base/'tampered-diagnostic-revision')

    def test_truncated_and_substituted_authored_scene_plans_fail_closed(self):
        self.add_render_scene_starts()
        self.detected_starts = [0, .125]

        def truncate(receipt, target):
            receipt['sampled_scene_count'] = 1
            receipt['scenes'] = receipt['scenes'][:1]
            receipt['artifacts_sha256'].pop('scene-02.png')
            (target/'scene-02.png').unlink()

        def substitute_id(receipt, target):
            receipt['scenes'][1]['scene_id'] = 's1'

        def substitute_frame(receipt, target):
            first, second = receipt['scenes']
            first['frame'], second['frame'] = second['frame'], first['frame']
            first['frame_sha256'], second['frame_sha256'] = (
                second['frame_sha256'], first['frame_sha256'])

        for index, mutation in enumerate((truncate, substitute_id, substitute_frame)):
            with self.subTest(mutation=mutation.__name__):
                output = self.base/f'malformed-plan-{index}'

                def sampler(root, target, *, timeout):
                    receipt = self.ready_sampler(root, target, timeout=timeout)
                    mutation(receipt, target)
                    review_fixture.write(target/'scene-review.json', receipt)
                    return receipt

                with patch.object(analyzer, '_run', side_effect=self.fake_run), patch(
                    'integrations.content_control.cycle_scene_review.make_scene_review',
                    side_effect=sampler
                ):
                    result = self.call(output)
                self.assertEqual(result['status'], 'DIAGNOSTIC_COMPLETE')
                review_fixture.write(self.packet.submitted,
                                     dict(self.packet.review, reviewed_at=result['finished_at']))
                with self.assertRaisesRegex(ValueError, 'incomplete|does not match|substituted'):
                    self.record(self.packet.submitted,
                                self.base/f'malformed-review-{index}.json',
                                rea_analysis=output/'analysis.json')

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
        submission = self.packet.submitted
        review_fixture.write(submission, dict(self.packet.review, reviewed_at=result['finished_at']))
        review = self.record(submission, self.packet.recorded,
                             rea_analysis=self.base/'analysis/analysis.json')
        self.assertEqual(review['rea_diagnostics']['status'], 'PARTIAL_DIAGNOSTIC')
        self.assertEqual(review['rea_diagnostics']['authored_cut_coverage']['status'], 'MISSING_AUTHORED_CUTS')
        self.assertFalse(review['full_av_review'])

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
