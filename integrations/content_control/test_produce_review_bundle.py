"""Boundaries only; actual inference evidence is recorded separately."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from integrations.content_control import produce_review_bundle as m
from integrations.content_control import runtime_doctor as doctor
from integrations.content_control.test_review_package import fixture as review_fixture


@contextmanager
def lease():yield None


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'bundle'
        self.options={'content_control_root':Path(self.temp.name),'source_commit':'a'*40,'source_manifest_sha256':'b'*64,
            'video_python':sys.executable,'picture_python':sys.executable,'otio_python':sys.executable,'timeout':30}
    def test_optional_stage_failure_is_persisted_as_blocked(self):
        self.output.mkdir();result={'steps':[]}
        def failing(*args,**kwargs):raise RuntimeError('optional diagnostic unavailable')
        with self.assertRaises(RuntimeError):
            m.execute_stage(result,self.output,'speech-diagnostic',['synthetic'],failing,time.monotonic()+1)
        self.assertEqual(result['steps'][0]['status'],'BLOCKED')
        self.assertEqual(json.loads((self.output/'bundle.json').read_text())['steps'][0]['status'],'BLOCKED')

    def test_partial_optional_diagnostic_configuration_blocked(self):
        result=m.produce_bundle(self.output,**self.options,dnsmos_python=sys.executable)
        self.assertEqual(result['status'],'BLOCKED');self.assertIn('both runtime',result['reason'])
        self.assertFalse(result['production_approved']);self.assertFalse((self.output/'review').exists())
    def test_source_mismatch_stops_before_loading_producer(self):
        with patch.object(m,'shared_admission_lock',lease),patch.object(m,'describe_source',return_value={'source_manifest_sha256':'c'*64}),patch.object(m,'inspect_runtime',return_value={'status':'PASS'}),patch.object(m,'producer_module') as producer:
            result=m.produce_bundle(self.output,**self.options)
        self.assertEqual(result['status'],'BLOCKED');self.assertIn('manifest',result['reason']);producer.assert_not_called()
    def test_budget_exhausted_before_producer(self):
        with patch.object(m,'shared_admission_lock',lease),patch.object(m,'describe_source',return_value={'source_manifest_sha256':'b'*64}),patch.object(m,'inspect_runtime',return_value={'status':'PASS'}),patch.object(m,'producer_module') as producer,patch.object(m.time,'monotonic',side_effect=[0,31]):
            result=m.produce_bundle(self.output,**self.options)
        self.assertEqual(result['status'],'BLOCKED');producer.assert_not_called()
    def test_existing_output_not_reused(self):
        self.output.mkdir();(self.output/'keep').write_text('yes')
        with self.assertRaises(FileExistsError):m.produce_bundle(self.output,**self.options)
        self.assertEqual((self.output/'keep').read_text(),'yes')
    def test_doctor_clamps_timeout_and_forwards_lease(self):
        from contextlib import contextmanager
        observed={}
        @contextmanager
        def fake_process(command,**kwargs):
            observed.update(kwargs)
            class Finished:
                returncode=0
                def poll(self):return 0
            yield Finished()
        with patch('integrations.owned_process.owned_process',fake_process):
            doctor.probe(['synthetic'],timeout=20,lease_fd=123,deadline=time.monotonic()+.2)
        self.assertGreater(observed['timeout'],0)
        self.assertLessEqual(observed['timeout'],.2)
        self.assertEqual(observed['lease_fd'],123)

    def test_doctor_expired_global_deadline_launches_nothing(self):
        with self.assertRaisesRegex(ValueError,'deadline_exhausted'):
            doctor.probe([sys.executable,'-c','raise AssertionError'],deadline=time.monotonic()-1)

    def build_review_fixture(self, *, corrupt_caption=False):
        source = Path(self.temp.name)
        narration = source/'public/audio/episode1-narration.mp3'
        narration.parent.mkdir(parents=True)
        narration.write_bytes(b'synthetic isolated narration')
        manifest = {'source_manifest_sha256': self.options['source_manifest_sha256'],
                    'source_files': {'public/audio/episode1-narration.mp3': m.digest(narration)}}
        observed = {}

        def produce(review, **kwargs):
            receipt = review_fixture(review)
            for name in ('encoded-verification.json','audio-verification.json'):
                (review/name).write_text('{}')
                receipt['artifacts_sha256'][name] = m.digest(review/name)
            receipt.update(source_inputs_unchanged=True, renderer_scratch_cleaned=True,
                           source_sha256=manifest['source_files'])
            m.write(review/'run.json',receipt)
            observed['receipt'] = receipt
            observed['original'] = {p.name:m.digest(p) for p in review.iterdir()}
            return receipt

        def argument(command, flag):
            return command[command.index(flag) + 1]

        def runner(command, *, cwd, log, deadline, env):
            receipt = observed['receipt']
            if log.name == 'automated-review.log':
                self.assertEqual(command[:3],[sys.executable,'-m','integrations.content_control.cycle_av_review'])
                self.assertEqual(Path(argument(command,'--input')),self.output/'review')
                self.assertEqual(Path(argument(command,'--output')),self.output/'automated-review.json')
                self.assertEqual(argument(command,'--candidate-sha256'),receipt['candidate_sha256'])
                self.assertEqual(argument(command,'--caption-sha256'),receipt['caption_sha256'])
                self.assertGreater(deadline,time.monotonic())
                m.write(self.output/'automated-review.json',{'schema_version':1,
                    'candidate_sha256':receipt['candidate_sha256'],
                    'caption_sha256':'0'*64 if corrupt_caption else receipt['caption_sha256'],
                    **{role:{'status':'BLOCKED'} for role in ('watcher','listener','analysis','competitor_comparison')},
                    'reviewer':{'status':'FULL_REVIEW_REQUIRED'},
                    **dict.fromkeys(('publication_enabled','paid_generation_enabled','production_approved',
                      'full_audiovisual_review_verified','competitor_audiovisual_comparison_verified'),False)})
            elif log.name == 'editable-export.log':
                edit = self.output/'edit';edit.mkdir()
                (edit/'timeline.otio').write_text('synthetic timeline')
                m.write(edit/'export-receipt.json',{'status':'INTERCHANGE_VERIFIED','roundtrip_verified':True,
                    'candidate_sha256':receipt['candidate_sha256'],'input_run_sha256':observed['original']['run.json'],
                    'publication_enabled':False,'production_approved':False,'files_sha256':{
                     'video.mp4':receipt['candidate_sha256'],'run.json':observed['original']['run.json'],
                     'timeline.otio':m.digest(edit/'timeline.otio')}})
                for name in ('video.mp4','run.json'):
                    (edit/name).write_bytes((self.output/'review'/name).read_bytes())
            elif log.name == 'speech-conversion.log':
                Path(command[-1]).write_bytes(b'synthetic converted narration')
            elif log.name == 'speech-diagnostic.log':
                m.write(log,{'status':'DIAGNOSTIC_COMPLETE','audio_sha256':m.digest(Path(argument(command,'--audio'))),
                    'publication_enabled':False,'production_approved':False,'full_av_review':False})
            else:
                self.fail(f'Unexpected stage: {log.name}')

        with patch.object(m,'shared_admission_lock',lease),patch.object(m,'describe_source',return_value=manifest), \
             patch.object(m,'inspect_runtime',return_value={'status':'PASS'}),patch.object(m,'producer_module') as producer, \
             patch.object(m,'guarded_runner',return_value=runner),patch.object(m.os,'sched_getaffinity',return_value={0,1}):
            producer.return_value.__enter__.return_value.produce.side_effect=produce
            result=m.produce_bundle(self.output,**dict(self.options,timeout=120),
                dnsmos_python=sys.executable,dnsmos_model=source/'synthetic.onnx')
        self.assertEqual(observed['original'],{p.name:m.digest(p) for p in (self.output/'review').iterdir()})
        return result

    def test_bundle_carries_guarded_automated_review_and_optional_speech_diagnostics(self):
        result=self.build_review_fixture()
        self.assertEqual(result['status'],'AWAITING_REVIEW',result)
        report=self.output/'automated-review.json'
        self.assertEqual(result['automated_review_sha256'],m.digest(report))
        self.assertEqual(result['delivery']['provenance']['automated_review_sha256'],m.digest(report))
        self.assertEqual(result['speech_diagnostic']['status'],'DIAGNOSTIC_COMPLETE')
        self.assertFalse(result['full_av_review']);self.assertFalse(result['production_approved'])
        with ZipFile(self.output/'delivery/review-package.zip') as archive:
            self.assertEqual(archive.read('review/automated-review.json'),report.read_bytes())
            self.assertIn('review/diagnostics/speech-diagnostic.json',archive.namelist())

    def test_bundle_blocks_mismatched_automated_report_before_delivery(self):
        result=self.build_review_fixture(corrupt_caption=True)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['failed_step'],'automated-review')
        self.assertEqual(result['steps'][-1]['status'],'BLOCKED')
        self.assertFalse((self.output/'delivery').exists())


if __name__=='__main__':unittest.main()
