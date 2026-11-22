import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_job import brief_digest, validate, check_completed, run_job, digest
from integrations.local_agent_queue import Queue, work


def brief():
    return {'schema_version': 1, 'title': 'Check the fee', 'topic': 'Annual fees',
            'sources': [{'id': 'cfpb', 'url': 'https://www.consumerfinance.gov/',
                         'retrieved_at': '2026-01-01T00:00:00Z', 'claim': 'Compare benefits and fees.',
                         'excerpt': 'Compare benefits and fees.'}],
            'reference_observations': [{'url': 'https://example.com/reference',
                                       'observed_at': '2026-01-01T00:00:00Z',
                                       'observation_type': 'transcript', 'patterns': ['A direct opening.']}],
            'scenes': [{'id': 'one', 'narration': 'Compare benefits and fees.',
                        'visual': 'Two columns', 'duration_seconds': 3, 'source_ids': ['cfpb']}]}


def request():
    value = brief()
    return {'operation': 'produce-content-cycle', 'brief': value, 'brief_sha256': brief_digest(value),
            'timeout_seconds': 60, 'publication_enabled': False, 'paid_generation_enabled': False}


def job():
    return {'id': 'new-video', 'adapter': 'content-control-cycle', 'request': request(),
            'max_attempts': 1, 'publication_enabled': False, 'paid_generation_enabled': False}


def write(path, value):
    path.write_text(json.dumps(value))


def packet(path, expected):
    path.mkdir()
    (path/'render').mkdir(); (path/'delivery').mkdir()
    (path/'render/video.mp4').write_bytes(b'candidate')
    from integrations.content_control.cycle_editorial import compile_editorial
    from integrations.content_control.cycle_job import canonical
    editorial = compile_editorial(brief())
    (path/'brief.json').write_text(canonical(brief()))
    write(path/'editorial.json', editorial)
    (path/'delivery/video.mp4').write_bytes(b'candidate')
    (path/'delivery/index.html').write_text('<html></html>')
    candidate = digest(path/'render/video.mp4')
    write(path/'delivery/editorial.json', editorial)
    (path/'render/captions.vtt').write_text('WEBVTT\n')
    (path/'delivery/captions.vtt').write_text('WEBVTT\n')
    from integrations.content_control.cycle_package import editorial_digest
    rendered = {'candidate_sha256': candidate, 'editorial_sha256': editorial_digest(editorial),
                'caption_sha256': digest(path/'render/captions.vtt'), 'status': 'AWAITING_REVIEW',
                'technical_status': 'PASS', 'publication_enabled': False, 'paid_generation_enabled': False,
                'production_approved': False, 'full_av_review': False}
    write(path/'render/render.json', rendered); write(path/'delivery/render.json', rendered)
    (path/'delivery/review-package.zip').write_bytes(b'archive')
    write(path/'delivery/package.json', dict(rendered, production_ready=False,
          render_receipt_sha256=digest(path/'render/render.json'), files_sha256={
          name: digest(path/'delivery'/name) for name in ('video.mp4', 'index.html', 'captions.vtt', 'render.json', 'editorial.json')}))
    receipt = {'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
               'publication_enabled': False, 'paid_generation_enabled': False,
               'production_approved': False, 'full_av_review': False,
               'production_ready': False, 'factual_review': False, 'competitor_comparison': False,
               'archive_sha256': digest(path/'delivery/review-package.zip'),
               'brief_sha256': expected, 'candidate_sha256': candidate,
               'editorial_sha256': digest(path/'editorial.json'),
               'package_sha256': digest(path/'delivery/package.json')}
    write(path/'cycle.json', receipt)
    return receipt


class CycleJobTests(unittest.TestCase):
    def test_completion_validates_optional_revision_lineage(self):
        from integrations.content_control.cycle_lineage import read_revision
        from integrations.content_control.test_cycle_lineage import handoff
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'cycle'
            expected = request()['brief_sha256']
            receipt = packet(root, expected)
            source = Path(td) / 'revision.json'
            write(source, handoff(expected))
            receipt['revision_lineage'] = read_revision(source, expected)
            write(root / 'cycle.json', receipt)
            check_completed(root, expected)
            receipt['revision_lineage']['revision_json'] += ' '
            write(root / 'cycle.json', receipt)
            with self.assertRaises(ValueError): check_completed(root, expected)

    def test_request_rejects_path_code_payment_and_changed_brief(self):
        validate(request())
        cases = []
        r = request(); r['voice_python'] = '/job/python'; cases.append(r)
        r = request(); r['paid_generation_enabled'] = True; cases.append(r)
        r = request(); r['brief']['title'] = 'changed'; cases.append(r)
        r = request(); r['timeout_seconds'] = True; cases.append(r)
        r = request(); r['brief']['scenes'][0]['source_ids'] = ['unknown']; r['brief_sha256'] = brief_digest(r['brief']); cases.append(r)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError): validate(value)

    def test_dispatch_uses_host_paths_and_same_durable_queue(self):
        with tempfile.TemporaryDirectory() as td:
            queue = Queue(Path(td)/'queue')
            try:
                queue.enqueue(job())
                with patch('integrations.content_control.cycle_job.run_job', return_value={
                        'status': 'PASS', 'review_status': 'AWAITING_REVIEW',
                        'publication_enabled': False, 'paid_generation_enabled': False}) as run:
                    work(queue, cycle_voice_python='/host/python', cycle_voice_root='/host/source',
                         cycle_transcription_python='/host/asr/python')
                self.assertEqual(run.call_args.kwargs, {'voice_python': '/host/python', 'voice_root': '/host/source', 'transcription_python': '/host/asr/python'})
                self.assertEqual(run.call_args.args[0], request())
                self.assertEqual(run.call_args.args[1], Path(td)/'queue/attempts/new-video/1')
                self.assertEqual(queue.get('new-video')['state'], 'succeeded')
            finally: queue.close()

    def test_delivered_bytes_and_approval_must_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'cycle'; receipt = packet(root, request()['brief_sha256'])
            check_completed(root, request()['brief_sha256'])
            (root/'delivery/index.html').write_text('changed')
            with self.assertRaises(ValueError): check_completed(root, request()['brief_sha256'])
            (root/'delivery/index.html').write_text('<html></html>')
            receipt['full_av_review'] = True; write(root/'cycle.json', receipt)
            with self.assertRaises(ValueError): check_completed(root, request()['brief_sha256'])

    def test_source_hash_mismatch_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'cycle'; packet(root, request()['brief_sha256'])
            with self.assertRaises(ValueError): check_completed(root, 'b'*64)
            (root/'render/escape').symlink_to('/tmp')
            with self.assertRaises(ValueError): check_completed(root, request()['brief_sha256'])

    def test_self_consistent_package_cannot_substitute_another_video(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'cycle'; receipt = packet(root, request()['brief_sha256'])
            (root/'delivery/video.mp4').write_bytes(b'different-candidate')
            package = json.loads((root/'delivery/package.json').read_text())
            package['files_sha256']['video.mp4'] = digest(root/'delivery/video.mp4')
            write(root/'delivery/package.json', package)
            receipt['package_sha256'] = digest(root/'delivery/package.json')
            write(root/'cycle.json', receipt)
            with self.assertRaisesRegex(ValueError, 'same editorial and candidate'):
                check_completed(root, request()['brief_sha256'])

    def test_self_consistent_package_cannot_substitute_editorial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'cycle'; receipt = packet(root, request()['brief_sha256'])
            (root/'delivery/editorial.json').write_text('{"title":"another story"}')
            package = json.loads((root/'delivery/package.json').read_text())
            package['files_sha256']['editorial.json'] = digest(root/'delivery/editorial.json')
            write(root/'delivery/package.json', package)
            receipt['package_sha256'] = digest(root/'delivery/package.json')
            write(root/'cycle.json', receipt)
            with self.assertRaisesRegex(ValueError, 'same editorial and candidate'):
                check_completed(root, request()['brief_sha256'])

    def test_unknown_capacity_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root/'source'; (source/'scripts').mkdir(parents=True)
            (source/'scripts/v2_free_voice.py').write_text('')
            attempt = root/'attempt'; attempt.mkdir()
            import sys
            with patch('integrations.content_control.cycle_job.collect_snapshot', return_value={}), \
                 patch('integrations.content_control.cycle_job.recommend_capacity', return_value={'admitted_workers': 0}), \
                 patch('integrations.content_control.cycle_job.guarded_runner') as runner:
                result = run_job(request(), attempt, voice_python=sys.executable, voice_root=source)
            self.assertEqual(result['status'], 'BLOCKED'); runner.assert_not_called()
            self.assertFalse(result['production_ready'])
            self.assertTrue((attempt/'cycle-adapter-receipt.json').is_file())

    def test_missing_host_runtime_is_blocked_not_success(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_job(request(), td)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertIn('Host must provide', result['blocker'])

    def test_real_sqlite_attempt_records_missing_runtime_as_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            queue = Queue(Path(td)/'queue')
            try:
                queue.enqueue(job())
                result = work(queue)
                self.assertEqual(result['processed'][0]['state'], 'blocked')
                stored = queue.get('new-video')['receipts'][0]['receipt']
                self.assertFalse(stored['production_ready'])
                disk = json.loads((Path(td)/'queue/attempts/new-video/1/cycle-adapter-receipt.json').read_text())
                self.assertEqual(disk, stored)
            finally: queue.close()

    def test_guardian_receives_fixed_command_and_packet_validation_controls_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root/'source'; (source/'scripts').mkdir(parents=True)
            (source/'scripts/v2_free_voice.py').write_text('')
            attempt = root/'attempt'; attempt.mkdir()
            import sys
            observed = []
            def run(command, **kwargs):
                observed.append((command, kwargs))
                packet(attempt/'cycle', request()['brief_sha256'])
            with patch('integrations.content_control.cycle_job.collect_snapshot', return_value={}), \
                 patch('integrations.content_control.cycle_job.recommend_capacity', return_value={'admitted_workers': 1}), \
                 patch('integrations.content_control.cycle_job.guarded_runner', return_value=run):
                result = run_job(request(), attempt, voice_python=sys.executable, voice_root=source)
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(result['review_status'], 'AWAITING_REVIEW')
            self.assertEqual(observed[0][0][0:2], [sys.executable, '-c'])
            self.assertEqual(observed[0][0][3], str(attempt/'brief.json'))
            self.assertEqual(observed[0][0][-2], '60')
            self.assertEqual(observed[0][0][-1], '')
            self.assertEqual(digest(attempt/'brief.json'), request()['brief_sha256'])


if __name__ == '__main__': unittest.main()
