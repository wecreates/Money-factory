"""Boundaries only; actual inference evidence is recorded separately."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from integrations.content_control import produce_review_bundle as m
from integrations.content_control import runtime_doctor as doctor


@contextmanager
def lease():yield None


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'bundle'
        self.options={'content_control_root':Path(self.temp.name),'source_commit':'a'*40,'source_manifest_sha256':'b'*64,
            'video_python':sys.executable,'picture_python':sys.executable,'otio_python':sys.executable,'timeout':30}
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


if __name__=='__main__':unittest.main()
