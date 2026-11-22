import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wholesale_doctor', Path(__file__).parent / 'wholesale/doctor.py')
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class WholesaleDoctorTests(unittest.TestCase):
    def test_missing_node_stops_before_output_or_execution(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(doctor.shutil, 'which', return_value=None):
            target=Path(directory)/'not-created'
            report,code=doctor.execute(target)
            self.assertEqual(code,1)
            self.assertTrue(any(x.startswith('NODE_REQUIRED') for x in report['dependencies']['errors']))
            self.assertFalse(target.exists())

    def test_unsupported_node_and_invalid_config_are_actionable(self):
        with patch.object(doctor.subprocess,'run') as run:
            run.return_value.stdout='v18.0.0'
            self.assertTrue(any(x.startswith('NODE_24_REQUIRED') for x in doctor.prerequisites()['errors']))
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'bad.json';source.write_text('{"password":"SYNTHETIC_SECRET"}')
            report,code=doctor.execute(Path(directory)/'unused',source)
            self.assertEqual(code,1);self.assertEqual(report['status'],'CONFIG_INVALID')
            self.assertNotIn('SYNTHETIC_SECRET',json.dumps(report))
            self.assertFalse((Path(directory)/'unused').exists())

    def test_real_worker_smoke_is_repeatable_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('first','second'):
                report,code=doctor.execute(Path(directory)/name)
                self.assertEqual(code,0,report)
                self.assertEqual(len(report['operations']),5)
                self.assertFalse(report['production_ready'])
                self.assertEqual(report['status'],'OFFLINE_SMOKE_PASSED_PRODUCTION_BLOCKED')
                self.assertEqual([x['readiness'] for x in report['operations'][2:]],['BLOCKED']*3)
            saved=(Path(directory)/'first/doctor-report.json').read_bytes()
            report,code=doctor.execute(Path(directory)/'first')
            self.assertEqual(code,1);self.assertEqual(report['status'],'OUTPUT_DIRECTORY_UNAVAILABLE')
            self.assertEqual((Path(directory)/'first/doctor-report.json').read_bytes(),saved)

    def test_check_only_does_not_claim_smoke_pass(self):
        report,code=doctor.execute(check_only=True)
        self.assertEqual(code,0);self.assertEqual(report['status'],'DEPENDENCIES_OK_SMOKE_NOT_RUN')
        self.assertEqual(report['operations'],[]);self.assertNotIn('output_directory',report)
