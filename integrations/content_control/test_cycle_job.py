import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_job import (
    brief_digest, validate, check_completed, run_job, digest, production_handoff,
)
from integrations.agent_capacity import AdmissionBusy
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


def intake_request(root, source):
    from integrations.content_control.cycle_intake import prepare_brief

    research, draft = root/'original-research.json', root/'original-draft.json'
    write(research, {key: source[key] for key in ('schema_version', 'topic', 'sources', 'reference_observations')})
    write(draft, {key: source[key] for key in ('schema_version', 'title', 'scenes')} |
          {'research_sha256': hashlib.sha256(research.read_bytes()).hexdigest()})
    ready = root/'intake'
    prepare_brief(research, draft, ready)
    brief_raw = (ready/'brief.json').read_bytes()
    value = json.loads(brief_raw)
    receipt_raw = (ready/'intake.json').read_bytes().replace(b'\n', b'\r\n')
    queued = dict(request(), brief=value, brief_sha256=brief_digest(value),
                  intake_input={'research_json': research.read_bytes().decode('utf-8'),
                                'draft_json': draft.read_bytes().decode('utf-8'),
                                'receipt_json': receipt_raw.decode('utf-8')})
    return queued, brief_raw


def write(path, value):
    path.write_text(json.dumps(value))


def synthetic_picture_mp4(path, seconds, *, audio_seconds=2):
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    f'color=c=black:s=90x160:r=24:d={seconds}',
                    '-f', 'lavfi', '-i', f'anullsrc=r=24000:cl=mono:d={audio_seconds}',
                    '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac',
                    str(path)], check=True, timeout=30)


def packet(path, expected, media=b'candidate', source_brief=None):
    path.mkdir()
    (path/'render').mkdir(); (path/'delivery').mkdir()
    (path/'render/video.mp4').write_bytes(media)
    from integrations.content_control.cycle_editorial import compile_editorial
    from integrations.content_control.cycle_job import canonical
    source = brief() if source_brief is None else source_brief
    editorial = compile_editorial(source)
    (path/'brief.json').write_text(canonical(source))
    write(path/'editorial.json', editorial)
    (path/'delivery/video.mp4').write_bytes(media)
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
    @staticmethod
    def idea_learning(*, audience=False):
        value = {'selection_receipt_sha256': '1' * 64,
                 'prior_candidate_sha256': '2' * 64,
                 'prior_package_sha256': '3' * 64,
                 'prior_thumbnail_sha256': '4' * 64,
                 'hypothesis_index': 1,
                 'hypothesis': 'Test simpler wording in the next unpublished candidate.',
                 'application': 'Use a shorter question in the next unpublished candidate.',
                 'prior_performance_status': 'UNAVAILABLE',
                 'audience_performance_verified': False}
        if audience:
            value.update(audience_observation_sha256='5' * 64,
                         audience_receipt_sha256='6' * 64,
                         prior_performance_status='SUPPLIED_UNVERIFIED')
        return value

    def test_queue_rejects_audience_bound_learning_but_retains_legacy_form(self):
        legacy = request(); legacy['brief']['idea_learning'] = self.idea_learning()
        legacy['brief_sha256'] = brief_digest(legacy['brief'])
        self.assertEqual(validate(legacy), legacy)
        audience = request(); audience['brief']['idea_learning'] = self.idea_learning(audience=True)
        audience['brief_sha256'] = brief_digest(audience['brief'])
        with self.assertRaisesRegex(ValueError, 'exact inline evidence replay'):
            validate(audience)

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

    def test_optional_minimum_duration_accepts_only_bounded_integer(self):
        self.assertEqual(validate(dict(request(), minimum_duration_seconds=510))['minimum_duration_seconds'], 510)
        for duration in (0, 601, True, None, '510', 510.0):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, 'Minimum duration'):
                validate(dict(request(), minimum_duration_seconds=duration))

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

    def test_dispatch_capacity_ceiling_is_host_only_and_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            queue = Queue(Path(td)/'queue')
            try:
                queue.enqueue(job())
                with patch('integrations.content_control.cycle_job.run_job', return_value={
                        'status': 'PASS', 'review_status': 'AWAITING_REVIEW',
                        'publication_enabled': False,
                        'paid_generation_enabled': False}) as run:
                    work(queue, cycle_voice_python='/host/python',
                         cycle_voice_root='/host/source',
                         cycle_capacity_cpu_cores=4,
                         cycle_capacity_memory_mb=6144)
                self.assertEqual(run.call_args.kwargs['capacity_cpu_cores'], 4)
                self.assertEqual(run.call_args.kwargs['capacity_memory_mb'], 6144)
                self.assertNotIn('capacity_cpu_cores', run.call_args.args[0])
                self.assertNotIn('capacity_memory_mb', run.call_args.args[0])
            finally:
                queue.close()

    def test_delivered_bytes_and_approval_must_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'cycle'; receipt = packet(root, request()['brief_sha256'])
            check_completed(root, request()['brief_sha256'])
            (root/'delivery/index.html').write_text('changed')
            with self.assertRaises(ValueError): check_completed(root, request()['brief_sha256'])
            (root/'delivery/index.html').write_text('<html></html>')
            receipt['full_av_review'] = True; write(root/'cycle.json', receipt)
            with self.assertRaises(ValueError): check_completed(root, request()['brief_sha256'])

    def test_worker_requires_bound_portrait_maximum_but_legacy_packet_remains_readable(self):
        from integrations.content_control.cycle_job import canonical
        queued = request()
        queued['brief']['portrait_handoff'] = {
            **dict.fromkeys(('candidate_sha256', 'cycle_sha256', 'brief_sha256', 'package_sha256', 'render_sha256'),
                            'a' * 64),
            'scenes': [{'scene_id': 'one', 'start_seconds': 10, 'end_seconds': 13}],
        }
        expected = queued['brief_sha256'] = brief_digest(queued['brief'])
        with self.assertRaisesRegex(ValueError, 'minimum exceeds'):
            validate(dict(queued, minimum_duration_seconds=61))
        validate(queued)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'cycle'
            receipt = packet(root, expected)
            (root/'brief.json').write_text(canonical(queued['brief']))
            check_completed(root, expected)
            with self.assertRaisesRegex(ValueError, 'maximum duration'):
                check_completed(root, expected, require_portrait_duration=True)
            baseline = json.loads((root/'render/render.json').read_text())
            baseline.update(maximum_duration_seconds=60, measured_narration_frame_budget=1440,
                            encoded_picture_duration_seconds=60, encoded_container_duration_seconds=60)
            package_path = root/'delivery/package.json'
            package = json.loads(package_path.read_text())
            receipt['maximum_duration_seconds'] = 60
            for update, success in (({}, True), ({'maximum_duration_seconds': 61}, False),
                                    ({'encoded_container_duration_seconds': 60.01}, False),
                                    ({'encoded_picture_duration_seconds': 60.01}, False),
                                    ({'measured_narration_frame_budget': 1441}, False)):
                with self.subTest(update=update):
                    rendered = {**baseline, **update}
                    write(root/'render/render.json', rendered)
                    write(root/'delivery/render.json', rendered)
                    package['media'] = {'duration_seconds': rendered['encoded_container_duration_seconds']}
                    package['render_receipt_sha256'] = package['files_sha256']['render.json'] = digest(root/'delivery/render.json')
                    write(package_path, package)
                    receipt['package_sha256'] = digest(package_path)
                    write(root/'cycle.json', receipt)
                    if success:
                        with patch('integrations.content_control.cycle_package.inspect_media',
                                   return_value={'picture_duration_seconds': 60, 'duration_seconds': 60}) as probe:
                            check_completed(root, expected, require_portrait_duration=True)
                        probe.assert_called_once_with(root/'delivery/video.mp4', deadline=None,
                                                      decode=False, include_picture_duration=True)
                    else:
                        with self.assertRaisesRegex(ValueError, 'maximum duration'):
                            check_completed(root, expected)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools unavailable')
    def test_maximum_is_measured_from_delivered_picture_and_container(self):
        from integrations.content_control.cycle_job import canonical
        from integrations.content_control.cycle_package import inspect_media

        source = brief()
        source['portrait_handoff'] = {
            **dict.fromkeys(('candidate_sha256', 'cycle_sha256', 'brief_sha256', 'package_sha256', 'render_sha256'),
                            'a' * 64),
            'scenes': [{'scene_id': 'one', 'start_seconds': 10, 'end_seconds': 13}],
        }
        expected = brief_digest(source)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for picture, audio, measured in ((1, 2, True), (61, 2, False), (1, 61, False), (1.5, 2, False)):
                with self.subTest(picture=picture, audio=audio):
                    video = root/f'{picture}-{audio}.mp4'
                    synthetic_picture_mp4(video, picture, audio_seconds=audio)
                    actual = inspect_media(video, decode=False, include_picture_duration=True)
                    self.assertEqual(actual['picture_duration_seconds'], picture)
                    if audio == 61:
                        self.assertGreater(actual['duration_seconds'], 60)
                    cycle = root/f'cycle-{picture}-{audio}'
                    receipt = packet(cycle, expected, video.read_bytes())
                    (cycle/'brief.json').write_text(canonical(source))
                    renderer_path = cycle/'render/render.json'
                    rendered = json.loads(renderer_path.read_text())
                    rendered.update(maximum_duration_seconds=60, measured_narration_frame_budget=24,
                                    encoded_picture_duration_seconds=1, encoded_container_duration_seconds=2)
                    write(renderer_path, rendered)
                    write(cycle/'delivery/render.json', rendered)
                    package_path = cycle/'delivery/package.json'
                    package = json.loads(package_path.read_text())
                    package['media'] = {'duration_seconds': 2}
                    package['render_receipt_sha256'] = package['files_sha256']['render.json'] = digest(renderer_path)
                    write(package_path, package)
                    receipt.update(maximum_duration_seconds=60, package_sha256=digest(package_path))
                    write(cycle/'cycle.json', receipt)
                    if measured:
                        self.assertEqual(check_completed(cycle, expected)['status'], 'AWAITING_REVIEW')
                    else:
                        with self.assertRaisesRegex(ValueError, 'portrait maximum duration evidence'):
                            check_completed(cycle, expected)

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

    def test_only_pre_execution_admission_contention_is_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root/'source'; (source/'scripts').mkdir(parents=True)
            (source/'scripts/v2_free_voice.py').write_text('')
            attempt = root/'attempt'; attempt.mkdir()
            import sys
            with patch('integrations.content_control.cycle_job.shared_admission_lock',
                       side_effect=AdmissionBusy('busy')):
                result = run_job(request(), attempt, voice_python=sys.executable, voice_root=source)
            self.assertTrue(result['retryable'])
            self.assertEqual(result['blocker'], 'AdmissionBusy')

            other = root/'other'; other.mkdir()
            blocked = run_job(request(), other)
            self.assertNotIn('retryable', blocked)

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
            self.assertEqual(observed[0][0][-4:], ['60', '', '', ''])
            self.assertEqual(digest(attempt/'brief.json'), request()['brief_sha256'])

    def test_inline_intake_binds_exact_bytes_and_keeps_queue_envelope_limit(self):
        from integrations.local_agent_queue import validate as validate_queue

        with tempfile.TemporaryDirectory() as td:
            queued, original = intake_request(Path(td), brief())
            self.assertEqual(validate_queue(dict(job(), request=queued))['request'], queued)
            raw, lineage, files, proof = production_handoff(queued)
            self.assertEqual(raw, original)
            self.assertIsNone(lineage)
            self.assertEqual(proof['intake_receipt_sha256'], hashlib.sha256(files['intake.json']).hexdigest())
            self.assertIn(b'\r\n', files['intake.json'])
            self.assertFalse(proof['factual_review'])
            for field in ('research_json', 'draft_json', 'receipt_json'):
                changed = copy.deepcopy(queued)
                changed['intake_input'][field] += ' '
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate(changed)
            with self.assertRaisesRegex(ValueError, 'exact inline'):
                validate(dict(queued, intake_input={**queued['intake_input'], 'path': 'outside'}))
            with self.assertRaisesRegex(ValueError, 'either the fresh intake or the revision'):
                validate(dict(queued, revision_input={}))
            self.assertEqual(validate(request()), request())

            # Both sources are below their individual limits and the extra whitespace is JSON-valid.
            # The unchanged durable envelope limit still rejects the combination before attempting a render.
            research = Path(td)/'original-research.json'
            draft = Path(td)/'original-draft.json'
            research.write_bytes(research.read_bytes() + b' ' * 80000)
            value = json.loads(draft.read_bytes())
            value['research_sha256'] = hashlib.sha256(research.read_bytes()).hexdigest()
            draft.write_bytes(json.dumps(value).encode('utf-8') + b' ' * 80000)
            from integrations.content_control.cycle_intake import prepare_brief
            second = Path(td)/'large-intake'
            prepare_brief(research, draft, second)
            value = json.loads((second/'brief.json').read_bytes())
            large = dict(queued, brief=value, brief_sha256=brief_digest(value),
                         intake_input={'research_json': research.read_text(), 'draft_json': draft.read_text(),
                                       'receipt_json': (second/'intake.json').read_text()})
            self.assertEqual(validate(large), large)
            with self.assertRaisesRegex(ValueError, 'oversized'):
                validate_queue(dict(job(), request=large))

    def test_guardian_intake_requires_matching_receipt_and_retained_files(self):
        import sys
        for outcome in ('match', 'drop', 'substitute', 'change-input'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root/'scripts').mkdir(); (root/'scripts/v2_free_voice.py').touch()
                attempt = root/'attempt'; attempt.mkdir()
                queued, original = intake_request(root, brief())
                _, _, files, proof = production_handoff(queued)

                def run(command, **kwargs):
                    self.assertIn('intake_inputs=dict(research_path=sys.argv[9],draft_path=sys.argv[10])', command[2])
                    self.assertEqual(command[-2:], [str(attempt/'research.json'), str(attempt/'draft.json')])
                    self.assertEqual((attempt/'brief.json').read_bytes(), original)
                    for name, raw in files.items():
                        self.assertEqual((attempt/name).read_bytes(), raw)
                    cycle = attempt/'cycle'
                    receipt = packet(cycle, proof['brief_sha256'], source_brief=queued['brief'])
                    (cycle/'brief.json').write_bytes(original)
                    if outcome != 'drop':
                        receipt['verified_intake'] = dict(proof)
                    if outcome == 'substitute':
                        receipt['verified_intake']['research_sha256'] = '0' * 64
                    if outcome == 'change-input':
                        (attempt/'intake.json').write_bytes(files['intake.json'].replace(b'\r\n', b'\n'))
                    write(cycle/'cycle.json', receipt)

                with patch('integrations.content_control.cycle_job.collect_snapshot', return_value={}), \
                     patch('integrations.content_control.cycle_job.recommend_capacity', return_value={'admitted_workers': 1}), \
                     patch('integrations.content_control.cycle_job.guarded_runner', return_value=run):
                    result = run_job(queued, attempt, voice_python=sys.executable, voice_root=root)
                self.assertEqual(result['status'], 'PASS' if outcome == 'match' else 'BLOCKED')
                if outcome == 'match':
                    self.assertEqual(result['verified_intake'], proof)
                else:
                    self.assertIn('differs from queued handoff', result['blocker'])

    def test_guardian_receives_minimum_and_missing_or_short_evidence_blocks_completion(self):
        import sys
        for outcome in ('missing', 'mismatch', 'short', 'pass'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root/'scripts').mkdir(); (root/'scripts/v2_free_voice.py').touch()
                attempt = root/'attempt'; attempt.mkdir()
                queued = dict(request(), minimum_duration_seconds=510)
                def run(command, **kwargs):
                    self.assertEqual(command[-1], '510')
                    self.assertIn('minimum_duration=int(sys.argv[8])', command[2])
                    cycle = attempt/'cycle'; receipt = packet(cycle, queued['brief_sha256'])
                    if outcome == 'missing': return
                    rendered = json.loads((cycle/'render/render.json').read_text())
                    minimum = 509 if outcome == 'mismatch' else 510
                    rendered.update(minimum_duration_seconds=minimum, measured_narration_frame_budget=12240,
                                    encoded_picture_duration_seconds=509.99 if outcome == 'short' else 510.0)
                    write(cycle/'render/render.json', rendered)
                    write(cycle/'delivery/render.json', rendered)
                    package = json.loads((cycle/'delivery/package.json').read_text())
                    package['render_receipt_sha256'] = digest(cycle/'delivery/render.json')
                    package['files_sha256']['render.json'] = package['render_receipt_sha256']
                    write(cycle/'delivery/package.json', package)
                    receipt.update(minimum_duration_seconds=minimum, package_sha256=digest(cycle/'delivery/package.json'))
                    write(cycle/'cycle.json', receipt)
                with patch('integrations.content_control.cycle_job.collect_snapshot', return_value={}), \
                     patch('integrations.content_control.cycle_job.recommend_capacity', return_value={'admitted_workers': 1}), \
                     patch('integrations.content_control.cycle_job.guarded_runner', return_value=run), \
                     patch('integrations.content_control.cycle_package.inspect_media',
                           return_value={'picture_duration_seconds': 510}) as probe:
                    result = run_job(queued, attempt, voice_python=sys.executable, voice_root=root)
                self.assertEqual(result['minimum_duration_seconds'], 510)
                self.assertEqual(result['status'], 'PASS' if outcome == 'pass' else 'BLOCKED')
                if outcome == 'pass':
                    self.assertEqual(probe.call_args.args, (attempt/'cycle/delivery/video.mp4',))
                    self.assertIsInstance(probe.call_args.kwargs['deadline'], float)
                    self.assertFalse(probe.call_args.kwargs['decode'])
                    self.assertTrue(probe.call_args.kwargs['include_picture_duration'])
                else:
                    self.assertIn('minimum', result['blocker'])
                    probe.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools unavailable')
    def test_minimum_is_measured_from_bound_picture_not_longer_audio_or_claims(self):
        from integrations.content_control.cycle_package import inspect_media

        expected = request()['brief_sha256']
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for picture_length in (0.5, 1, 1.5):
                with self.subTest(picture_length=picture_length):
                    media = root/f'{picture_length}.mp4'
                    synthetic_picture_mp4(media, picture_length)
                    self.assertGreater(inspect_media(media, decode=False)['duration_seconds'], 1)
                    cycle = root/f'cycle-{picture_length}'
                    receipt = packet(cycle, expected, media.read_bytes())
                    rendered = json.loads((cycle/'render/render.json').read_text())
                    rendered.update(minimum_duration_seconds=1, measured_narration_frame_budget=24,
                                    encoded_picture_duration_seconds=1)
                    write(cycle/'render/render.json', rendered)
                    write(cycle/'delivery/render.json', rendered)
                    package_path = cycle/'delivery/package.json'
                    package = json.loads(package_path.read_text())
                    renderer_hash = digest(cycle/'delivery/render.json')
                    package['render_receipt_sha256'] = package['files_sha256']['render.json'] = renderer_hash
                    write(package_path, package)
                    receipt.update(minimum_duration_seconds=1, package_sha256=digest(package_path))
                    write(cycle/'cycle.json', receipt)
                    if picture_length == 1:
                        result = check_completed(cycle, expected, minimum_duration=1)
                        self.assertEqual(result['status'], 'AWAITING_REVIEW')
                    else:
                        with self.assertRaisesRegex(ValueError, 'minimum picture duration'):
                            check_completed(cycle, expected, minimum_duration=1)


class QueuedRevisionTests(unittest.TestCase):
    def request(self, raw=None):
        from integrations.content_control.cycle_lineage import SCOPE
        from integrations.content_control.test_cycle_lineage import handoff
        import hashlib
        value = request()
        raw = raw if raw is not None else json.dumps(value['brief'], indent=2) + '\n'
        receipt = json.dumps(handoff(hashlib.sha256(raw.encode()).hexdigest()), indent=2) + '\n'
        value['revision_input'] = {'brief_json': raw, 'revision_lineage': {
            'schema_version': 1, 'revision_json': receipt,
            'revision_sha256': hashlib.sha256(receipt.encode()).hexdigest(),
            'parent_evidence_independently_verified': False,
            'feedback_resolution_verified': False, 'scope': SCOPE}}
        return value

    def test_whitespace_is_retained_and_old_request_still_works(self):
        from integrations.content_control.cycle_job import production_input
        value = self.request()
        validate(value); validate(request())
        encoded, lineage = production_input(value)
        self.assertEqual(encoded, value['revision_input']['brief_json'].encode())
        import hashlib
        self.assertNotEqual(hashlib.sha256(encoded).hexdigest(), value['brief_sha256'])
        self.assertEqual(production_input(request())[1], None)

    def test_invalid_revision_inputs_rejected(self):
        cases = []
        v = self.request(); v['revision_input']['path'] = '/not/data'; cases.append(v)
        v = self.request(); v['revision_input']['brief_json'] += ' '; cases.append(v)
        v = self.request(); v['revision_input']['brief_json'] = ' ' * (256*1024+1); cases.append(v)
        v = self.request(); v['revision_input']['revision_lineage']['feedback_resolution_verified'] = True; cases.append(v)
        v = self.request(); v['revision_input']['brief_json'] = '{"schema_version":1,"schema_version":1}'; cases.append(v)
        v = self.request(); v['revision_input']['brief_json'] = '\ud800'; cases.append(v)
        altered = brief(); altered['title'] = 'Different title'
        cases.append(self.request(json.dumps(altered)))
        for value in cases:
            with self.subTest(value=repr(value)[:100]), self.assertRaises(ValueError): validate(value)

    def test_guardian_preserves_handoff_and_rejects_drop_or_substitution(self):
        from integrations.content_control.cycle_job import production_input
        import sys
        for kind in ('match', 'drop', 'substitute'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td); source = root/'source'; (source/'scripts').mkdir(parents=True)
                (source/'scripts/v2_free_voice.py').write_text('')
                attempt = root/'attempt'; attempt.mkdir()
                value = self.request(); encoded, lineage = production_input(value)
                def run(command, **kwargs):
                    self.assertEqual(command[-2:], [str(attempt/'revision.json'), ''])
                    self.assertIn('revision_path=sys.argv[7] or None', command[2])
                    self.assertEqual((attempt/'brief.json').read_bytes(), encoded)
                    self.assertEqual((attempt/'revision.json').read_bytes(), lineage['revision_json'].encode())
                    receipt = packet(attempt/'cycle', digest(attempt/'brief.json'))
                    (attempt/'cycle/brief.json').write_bytes(encoded)
                    if kind != 'drop':
                        receipt['revision_lineage'] = copy.deepcopy(lineage)
                    if kind == 'substitute':
                        import hashlib
                        alternate = json.loads(lineage['revision_json'])
                        alternate['recorded_review_sha256'] = 'f'*64
                        raw = json.dumps(alternate)
                        receipt['revision_lineage']['revision_json'] = raw
                        receipt['revision_lineage']['revision_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
                    write(attempt/'cycle/cycle.json', receipt)
                with patch('integrations.content_control.cycle_job.collect_snapshot', return_value={}), \
                     patch('integrations.content_control.cycle_job.recommend_capacity', return_value={'admitted_workers': 1}), \
                     patch('integrations.content_control.cycle_job.guarded_runner', return_value=run):
                    result = run_job(value, attempt, voice_python=sys.executable, voice_root=source)
                self.assertEqual(result['status'], 'PASS' if kind == 'match' else 'BLOCKED')
                self.assertEqual(result['brief_sha256'], value['brief_sha256'])
                self.assertEqual(result['production_brief_sha256'], digest(attempt/'brief.json'))
                if kind != 'match': self.assertIn('differs from queued', result['blocker'])

    def test_real_queue_roundtrip_preserves_revision_request(self):
        with tempfile.TemporaryDirectory() as td:
            queued = job(); queued['request'] = self.request()
            queue = Queue(Path(td)/'queue')
            queue.enqueue(queued); queue.close()
            queue = Queue(Path(td)/'queue')
            try:
                with patch('integrations.content_control.cycle_job.run_job', return_value={
                        'status': 'BLOCKED', 'publication_enabled': False, 'paid_generation_enabled': False}) as adapter:
                    work(queue)
                self.assertEqual(adapter.call_args.args[0], queued['request'])
            finally: queue.close()


if __name__ == '__main__': unittest.main()
