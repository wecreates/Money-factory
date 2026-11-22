"""Source tamper tests use disposable Git repos; runtime unit probes are fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import venv
import unittest
from unittest.mock import patch

from integrations.content_control import runtime_doctor as doctor


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.git('init', '-q')
        for name in doctor.SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}' if name.endswith('.json') else 'fixture\n')
        for name in ('state/episode1-factual-contract.json', 'state/episode1-sync-contract.json'):
            (self.root / name).write_text('{"publication_enabled":false}')
        (self.root / 'scripts/produce_episode1_review.py').write_text(
            'SOURCES = ' + repr(doctor.SOURCES) + '\ndef produce(output, *, command_runner=None): pass\n')
        self.commit()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')

    def test_manifest_binds_every_tracked_input_and_commit(self):
        from integrations.owned_process import owned_process
        with tempfile.TemporaryFile() as lease, patch('integrations.owned_process.owned_process', wraps=owned_process) as guardian:
            report = doctor.describe_source(self.root, self.git('rev-parse', 'HEAD'), lease_fd=lease.fileno())
            self.assertTrue(guardian.call_count)
            self.assertTrue(all(call.kwargs['lease_fd'] == lease.fileno() for call in guardian.call_args_list))
        self.assertEqual(report['source_count'], 22)
        expected = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in doctor.SOURCES}
        self.assertEqual(report['source_files'], expected)
        self.assertEqual(report['source_manifest_sha256'], hashlib.sha256(doctor.canonical(expected).encode()).hexdigest())

    def test_wrong_commit_or_missing_owned_runner_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source_commit_mismatch'):
            doctor.describe_source(self.root, '0' * 40)
        script = self.root / 'scripts/produce_episode1_review.py'
        script.write_text(script.read_text().replace('*, command_runner=None', '*, timeout=30'))
        self.commit()
        with self.assertRaisesRegex(ValueError, 'owned_command_runner_interface_missing'):
            doctor.describe_source(self.root)

    def test_dirty_asset_even_assume_unchanged_is_rejected(self):
        name = 'public/audio/episode1-narration.mp3'
        self.git('update-index', '--assume-unchanged', name)
        (self.root / name).write_bytes(b'replaced narration')
        with self.assertRaisesRegex(ValueError, 'source_bytes_differ_from_commit'):
            doctor.describe_source(self.root)

    def test_untracked_python_shadow_rejected(self):
        (self.root / 'scripts/json.py').write_text('raise SystemExit("should never execute")')
        with self.assertRaisesRegex(ValueError, 'untracked_executable_source'):
            doctor.describe_source(self.root)

    def test_source_is_parsed_without_execution(self):
        marker = self.root / 'executed'
        script = self.root / 'scripts/produce_episode1_review.py'
        script.write_text(f'open({str(marker)!r},"w").write("bad")\nSOURCES = tuple()\n')
        self.commit()
        with self.assertRaises(ValueError):
            doctor.describe_source(self.root)
        self.assertFalse(marker.exists())

    def test_committed_symlink_or_publication_contract_is_rejected(self):
        name = 'public/audio/episode1-sfx-1.mp3'
        (self.root / name).unlink()
        (self.root / name).symlink_to('episode1-sfx-2.mp3')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'source_symlink_forbidden'):
            doctor.describe_source(self.root)

    def test_publication_discrepancy_is_rejected(self):
        (self.root / 'state/episode1-factual-contract.json').write_text('{"publication_enabled":true}')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'source_publication_contract_not_disabled'):
            doctor.describe_source(self.root)

    def test_diagnose_does_not_probe_runtime_when_source_invalid(self):
        with patch.object(doctor, 'inspect_runtime', side_effect=AssertionError('Unverified source used')):
            report = doctor.diagnose(self.root, video_python='/no/runtime', picture_python='/no/runtime', expected_commit='0'*40)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertIs(report['production_ready'], False)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.hub = self.root / 'hub'
        self.revision = 'a' * 40
        model = self.hub / 'models--Systran--faster-whisper-base.en'
        (model / 'refs').mkdir(parents=True)
        (model / 'refs/main').write_text(self.revision)
        self.snapshot = model / 'snapshots' / self.revision
        self.snapshot.mkdir(parents=True)
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
            (self.snapshot / name).write_text('fixture')
        locked = {}
        for name in ('react', 'react-dom', 'remotion', 'esbuild'):
            directory = self.root / 'node_modules' / name
            directory.mkdir(parents=True)
            (directory / 'package.json').write_text('{"version":"1.0.0"}')
            locked['node_modules/'+name] = {'version': '1.0.0'}
        (self.root / 'package-lock.json').write_text(json.dumps({'packages': locked}))
        self.environment = patch.dict(os.environ, {'HF_HUB_CACHE': str(self.hub)})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def probe(self, command, **options):
        if command[0] == 'video-python': return 'CYZOR_RUNTIME={"python":[3,12,0],"version":"1.2.1"}'
        if command[0] == 'picture-python': return 'CYZOR_RUNTIME={"python":[3,12,0],"version":"2.9.1"}'
        if command[0] == 'node': return 'v24.22.3\n'
        if '-filters' in command: return ' subtitles amix adelay tpad fps volumedetect ebur128 astats silencedetect '
        if '-encoders' in command: return ' libx264 aac '
        if command[0] == 'fc-match': return 'DejaVu Sans'
        return 'fixture FFmpeg version'

    def inspect(self):
        with patch.object(doctor, 'probe', side_effect=self.probe):
            return doctor.inspect_runtime(self.root, video_python='video-python', picture_python='picture-python')

    def test_complete_prerequisites_are_not_inference_claim(self):
        report = self.inspect()
        self.assertEqual(report['status'], 'PASS')
        self.assertIn('no inference', report['scope'])
        self.assertEqual(report['details']['cached_asr']['revision'], self.revision)

    def test_native_library_stdout_does_not_hide_valid_runtime_metadata(self):
        original = self.probe
        with patch.object(doctor, 'probe', side_effect=lambda command, **kw: 'native library diagnostic\n' + original(command, **kw) if command[0] == 'video-python' else original(command, **kw)):
            report = doctor.inspect_runtime(self.root, video_python='video-python', picture_python='picture-python')
        self.assertTrue(report['checks']['transcription_python'])

    def test_runtime_probes_forward_active_admission_descriptor(self):
        with patch.object(doctor, 'probe', side_effect=self.probe) as probe:
            report = doctor.inspect_runtime(self.root, 'video-python', 'picture-python', lease_fd=42)
        self.assertEqual(report['status'], 'PASS')
        self.assertTrue(probe.call_count)
        self.assertTrue(all(call.kwargs['lease_fd'] == 42 for call in probe.call_args_list))

    def test_real_isolated_python_blocks_foreign_regular_scripts_package(self):
        environment = self.root / 'runtime'
        venv.EnvBuilder(with_pip=False).create(environment)
        interpreter = environment / 'bin/python'
        site = environment / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        for module in ('faster_whisper', 'ctranslate2', 'numpy'):
            (site / (module + '.py')).write_text('# Runtime fixture, no model execution\n')
        metadata = site / 'faster_whisper-1.2.1.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_text('Name: faster-whisper\nVersion: 1.2.1\n')
        foreign = site / 'scripts'
        foreign.mkdir()
        (foreign / '__init__.py').write_text('# Conflicting installed regular package\n')
        real_probe = doctor.probe
        def mixed_probe(command, **kwargs):
            return real_probe(command, **kwargs) if command[0] == str(interpreter) else self.probe(command, **kwargs)
        with patch.object(doctor, 'probe', side_effect=mixed_probe):
            blocked = doctor.inspect_runtime(self.root, str(interpreter), 'picture-python')
            self.assertIn('transcription_python', blocked['blockers'])
            (foreign / '__init__.py').unlink()
            clear = doctor.inspect_runtime(self.root, str(interpreter), 'picture-python')
            self.assertTrue(clear['checks']['transcription_python'])

    def test_missing_cached_weights_blocks_without_downloading(self):
        (self.snapshot / 'model.bin').unlink()
        report = self.inspect()
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertIn('cached_asr', report['blockers'])
        self.assertFalse((self.snapshot / 'model.bin').exists())

    def test_npm_version_mismatch_is_not_available(self):
        (self.root / 'node_modules/react/package.json').write_text('{"version":"2.0.0"}')
        self.assertIn('npm_packages', self.inspect()['blockers'])

    def test_missing_ffmpeg_capability_blocks(self):
        original = self.probe
        with patch.object(doctor, 'probe', side_effect=lambda command, **kw: ' amix ' if '-filters' in command else original(command, **kw)):
            report = doctor.inspect_runtime(self.root, video_python='video-python', picture_python='picture-python')
        self.assertIn('ffmpeg', report['blockers'])

    def test_ambient_credentials_and_runtime_hooks_not_forwarded(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-secret', 'NODE_OPTIONS': '--require bad', 'PYTHONPATH': '/untrusted', 'HTTP_PROXY': 'fixture'}):
            env = doctor.safe_environment()
        self.assertTrue({'OPENAI_API_KEY', 'NODE_OPTIONS', 'PYTHONPATH', 'HTTP_PROXY'}.isdisjoint(env))
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')


if __name__ == '__main__':
    unittest.main()
