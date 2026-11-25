"""Durable retained-review adapter tests; review semantics are exercised elsewhere."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_review_job import (
    _bounded_call, _export_review, check_completed, run_job, validate,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spawn_blocking_child(marker):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    Path(marker).write_text(str(child.pid))
    child.wait()


def process_running(pid):
    status = Path('/proc') / str(pid) / 'stat'
    if not status.exists():
        return False
    return status.read_text().split()[2] != 'Z'


class RetainedReviewJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.cycle = self.base / 'cycle'
        write(self.cycle / 'delivery/captions.vtt', {'fixture': 'captions'})
        write(self.cycle / 'delivery/package.json', {'fixture': 'package'})
        write(self.cycle / 'delivery/review-package.zip', {'fixture': 'archive'})
        (self.cycle / 'delivery/video.mp4').write_bytes(b'candidate')
        self.analysis = self.base / 'analysis'
        write(self.analysis / 'diagnostics/result.json', {'fixture': 'diagnostic'})
        write(self.analysis / 'analysis.json', {'fixture': 'analysis'})
        self.submitted = self.base / 'submitted.json'
        write(self.submitted, {
            'candidate_sha256': self.candidate if hasattr(self, 'candidate') else 'fixture',
            'reviewer': 'Fixture reviewer',
            'reviewed_at': '2026-01-02T00:00:00Z',
            'checks': {'factual_accuracy': {
                'passed': True, 'evidence': 'Fixture factual evidence statement.',
            }},
        })
        self.candidate = digest(self.cycle / 'delivery/video.mp4')
        submitted = json.loads(self.submitted.read_text())
        submitted['candidate_sha256'] = self.candidate
        write(self.submitted, submitted)
        self.snapshot = {
            'candidate_sha256': self.candidate,
            'files_sha256': {
                'delivery/captions.vtt': digest(self.cycle / 'delivery/captions.vtt'),
                'delivery/package.json': digest(self.cycle / 'delivery/package.json'),
                'delivery/review-package.zip': digest(self.cycle / 'delivery/review-package.zip'),
            },
        }
        self.request = {
            'operation': 'record-retained-rea-review',
            'candidate_sha256': self.candidate,
            'caption_sha256': self.snapshot['files_sha256']['delivery/captions.vtt'],
            'package_sha256': self.snapshot['files_sha256']['delivery/package.json'],
            'review_archive_sha256': self.snapshot['files_sha256']['delivery/review-package.zip'],
            'rea_receipt_sha256': digest(self.analysis / 'analysis.json'),
            'submitted_review_sha256': digest(self.submitted),
            'timeout_seconds': 30,
            'publication_enabled': False,
            'paid_generation_enabled': False,
            'production_approved': False,
            'production_ready': False,
            'full_av_review': False,
        }
        self.evidence = {
            'receipt_sha256': self.request['rea_receipt_sha256'],
            'authored_cut_coverage': {'status': 'COMPLETE'},
            'authored_scene_samples': {'status': 'SCENE_SAMPLES_READY'},
        }
        self.attempt = self.base / 'queue/attempts/job/1'
        self.attempt.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def _record(self, cycle, submitted, output, *, rea_analysis):
        result = {
            'schema_version': 1,
            'status': 'REVISION_REQUIRED',
            'candidate_sha256': self.candidate,
            'reviewer': 'Fixture reviewer',
            'reviewed_at': '2026-01-02T00:00:00+00:00',
            'recorded_at': '2026-01-02T00:01:00+00:00',
            'checks': {'factual_accuracy': {
                'passed': True, 'evidence': 'Fixture factual evidence statement.',
            }},
            'feedback': [{'check': 'full_audiovisual', 'action': 'Complete review.'}],
            'source_files_sha256': self.snapshot['files_sha256'],
            'submitted_review_sha256': self.request['submitted_review_sha256'],
            'independent_verification': False,
            'scope': ('Candidate-bound reviewer attestation only; supplied judgments '
                      'are not independently verified.'),
            'rea_diagnostics': self.evidence,
            'publication_enabled': False,
            'paid_generation_enabled': False,
            'production_approved': False,
            'production_ready': False,
            'full_av_review': False,
        }
        write(Path(output), result)
        return result

    def _run(self):
        with patch('integrations.content_control.cycle_review.inspect_cycle',
                   return_value=self.snapshot), \
             patch('integrations.rea_video.analyze_cycle.review_evidence',
                   return_value=(self.evidence, lambda: None)), \
             patch('integrations.content_control.cycle_review.record_review',
                   side_effect=self._record):
            return run_job(
                self.request, self.attempt, cycle_review_root=self.cycle,
                rea_analysis_root=self.analysis,
                submitted_review_path=self.submitted)

    def _check(self, receipt):
        with patch('integrations.content_control.cycle_review.inspect_cycle',
                   return_value=self.snapshot), \
             patch('integrations.rea_video.analyze_cycle.review_evidence',
                   return_value=(self.evidence, lambda: None)):
            return check_completed(self.attempt, self.request, receipt)

    def _rebuild_export(self, review):
        write(self.attempt / 'recorded-review.json', review)
        delivery = self.attempt / 'delivery'
        shutil.rmtree(delivery)
        return _export_review(
            delivery, self.attempt / 'inputs/rea-analysis/analysis.json',
            self.attempt / 'inputs/submitted-review.json',
            self.attempt / 'recorded-review.json', self.request,
            time.monotonic() + 10)

    def test_rejects_unknown_fields_and_enabled_gates(self):
        changed = dict(self.request, extra=True)
        with self.assertRaisesRegex(ValueError, 'exact documented'):
            validate(changed)
        changed = dict(self.request, publication_enabled=True)
        with self.assertRaisesRegex(ValueError, 'must remain false'):
            validate(changed)

    def test_retains_exact_inputs_exports_review_and_rechecks_after_restart(self):
        result = self._run()
        restarted = self._check(result)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['review_status'], 'REVISION_REQUIRED')
        self.assertEqual(restarted['recorded_review_sha256'],
                         result['recorded_review_sha256'])
        self.assertEqual(digest(self.attempt / 'inputs/rea-analysis/analysis.json'),
                         self.request['rea_receipt_sha256'])
        self.assertEqual(digest(self.attempt / 'inputs/submitted-review.json'),
                         self.request['submitted_review_sha256'])
        self.assertEqual(digest(self.attempt / 'delivery/review-export.zip'),
                         result['review_export_sha256'])
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['paid_generation_enabled'])

    def test_blocks_mismatched_source_without_creating_review_export(self):
        changed = dict(self.request, candidate_sha256='0' * 64)
        with patch('integrations.content_control.cycle_review.inspect_cycle',
                   return_value=self.snapshot):
            result = run_job(
                changed, self.attempt, cycle_review_root=self.cycle,
                rea_analysis_root=self.analysis,
                submitted_review_path=self.submitted)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('immutable queue pins', result['blocker'])
        self.assertFalse((self.attempt / 'delivery').exists())

    def test_rebuilt_valid_shape_export_cannot_escape_durable_receipt_hashes(self):
        receipt = self._run()
        changed = json.loads((self.attempt / 'recorded-review.json').read_text())
        changed['recorded_at'] = '2026-01-02T00:02:00+00:00'
        self._rebuild_export(changed)
        with self.assertRaisesRegex(ValueError, 'Durable receipt does not bind'):
            self._check(receipt)

    def test_fabricated_status_and_rebuilt_zip_fail_strict_review_validation(self):
        receipt = self._run()
        changed = json.loads((self.attempt / 'recorded-review.json').read_text())
        changed['status'] = 'EDITORIAL_REVIEW_RECORDED'
        manifest_sha, archive_sha = self._rebuild_export(changed)
        forged = dict(receipt, review_status=changed['status'],
                      recorded_review_sha256=digest(self.attempt / 'recorded-review.json'),
                      review_manifest_sha256=manifest_sha,
                      review_export_sha256=archive_sha)
        write(self.attempt / 'cycle-review-adapter-receipt.json', forged)
        with self.assertRaisesRegex(ValueError, 'identity, status, or scope'):
            self._check(forged)

    def test_root_recorded_copy_must_match_exported_copy(self):
        receipt = self._run()
        changed = json.loads((self.attempt / 'recorded-review.json').read_text())
        changed['recorded_at'] = '2026-01-02T00:02:00+00:00'
        write(self.attempt / 'recorded-review.json', changed)
        with self.assertRaisesRegex(ValueError, 'root and delivery copies differ'):
            self._check(receipt)

    def test_blocking_review_primitive_is_hard_bounded(self):
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, 'fixture block'):
            _bounded_call(time.monotonic() + .05, 'fixture block', time.sleep, 5)
        self.assertLess(time.monotonic() - started, 1)

    def test_pre_setsid_timeout_uses_direct_kill_without_unbounded_join(self):
        started = time.monotonic()
        with patch('integrations.content_control.cycle_review_job.os.setsid',
                   side_effect=lambda: time.sleep(2)), \
             self.assertRaisesRegex(TimeoutError, 'pre-session fixture'):
            _bounded_call(time.monotonic() + .05, 'pre-session fixture', time.sleep, 5)
        self.assertLess(time.monotonic() - started, 1)

    def test_missing_process_group_falls_back_to_bounded_direct_kill(self):
        started = time.monotonic()
        with patch('integrations.content_control.cycle_review_job.os.killpg',
                   side_effect=ProcessLookupError), \
             self.assertRaisesRegex(TimeoutError, 'missing-group fixture'):
            _bounded_call(time.monotonic() + .05, 'missing-group fixture', time.sleep, 5)
        self.assertLess(time.monotonic() - started, 1)

    @unittest.skipUnless(Path('/proc').is_dir(), 'Live descendant check requires procfs')
    def test_established_group_timeout_leaves_no_live_descendant(self):
        marker = self.base / 'descendant.pid'
        with self.assertRaisesRegex(TimeoutError, 'descendant fixture'):
            _bounded_call(time.monotonic() + .3, 'descendant fixture',
                          spawn_blocking_child, marker)
        self.assertTrue(marker.exists())
        pid = int(marker.read_text())
        deadline = time.monotonic() + 1
        while process_running(pid) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(process_running(pid))
