"""Receipt scope must hold even when all child-supplied hashes are valid."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from production_test_fixtures import artifact_bodies

module = importlib.util.spec_from_file_location('scope_agent', Path(__file__).with_name('production_agent.py'))
agent = importlib.util.module_from_spec(module); module.loader.exec_module(agent)
CHECKS = ['official_template', 'rights', 'editorial', 'independent_visual_review',
          'marketplace_account', 'platform_preview', 'release_approval']


class ProductionScopeTests(unittest.TestCase):
    def attempt(self, *, platform='kdp', result_change=None, manifest_change=None, empty=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root/'job.json'; font = root/'font.ttf'; out = root/'out'
            job.write_text(json.dumps({'publication_enabled': False, 'paid_generation_enabled': False,
                                       'platform': platform}))
            font.write_bytes(b'fixture')
            def child(argv, **kwargs):
                package = out/'package'; package.mkdir(parents=True)
                bodies = artifact_bodies(platform, {'art.bin': 'Étoile fixture'.encode()})
                for name,body in bodies.items(): (package/name).write_bytes(body)
                manifest = {'schema_version': 1, 'platform': platform, 'publication_enabled': False,
                            'files': {} if empty else {name:hashlib.sha256(body).hexdigest() for name,body in bodies.items()}}
                if manifest_change: manifest_change(manifest)
                digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                                                   ensure_ascii=False).encode()).hexdigest()
                manifest['package_sha256'] = digest
                result = {'schema_version': 1, 'platform': platform, 'status': 'REVIEW_REQUIRED',
                          'publication_enabled': False, 'production_ready': False,
                          'paid_generation_enabled': False, 'marketplace_ready': False,
                          'remaining_checks': CHECKS.copy(), 'package_sha256': digest}
                if result_change: result_change(result)
                (package/'manifest.json').write_text(json.dumps(manifest))
                (out/'result.json').write_text(json.dumps(result))
            with patch.object(agent, 'run_review_child', side_effect=child):
                try:
                    result = agent.run(job, root, font, out)
                except ValueError:
                    self.assertFalse((out/'money-factory-receipt.json').exists())
                    if out.exists(): self.assertTrue((out/'package/art.bin').exists())
                    raise
            self.assertEqual(json.loads((out/'money-factory-receipt.json').read_text()), result)
            self.assertEqual(result['input_sha256'], hashlib.sha256(job.read_bytes()).hexdigest())
            return result

    def test_all_supported_platforms_keep_review_only_receipts(self):
        for platform in ('kdp', 'redbubble', 'teepublic', 'zazzle', 'spreadshirt'):
            with self.subTest(platform=platform):
                result = self.attempt(platform=platform)
                self.assertEqual(result['platform'], platform)
                self.assertEqual(result['remaining_checks'], CHECKS)

    def test_unsupported_job_never_starts_child(self):
        for platform in ('etsy', '', None, [], 1):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); job = root/'job.json'
                job.write_text(json.dumps({'publication_enabled': False,
                    'paid_generation_enabled': False, 'platform': platform}))
                with patch.object(agent, 'run_review_child') as child:
                    with self.assertRaisesRegex(ValueError, '^PLATFORM_BLOCKED$'):
                        agent.run(job, root, root/'absent-font', root/'out')
                    child.assert_not_called()

    def test_all_readiness_flags_must_be_explicit_false(self):
        for field in ('publication_enabled', 'production_ready', 'paid_generation_enabled', 'marketplace_ready'):
            for value in (True, None, 0, 'false'):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, '^RESULT_SCOPE_INVALID$'):
                        self.attempt(result_change=lambda r: r.update({field: value}))
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, '^RESULT_SCOPE_INVALID$'):
                self.attempt(result_change=lambda r: r.pop(field))

    def test_result_version_and_platform_bind_to_job(self):
        for field, value in (('schema_version', True), ('schema_version', 1.0),
                             ('schema_version', 2), ('platform', 'redbubble'), ('platform', 'etsy')):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, '^RESULT_SCOPE_INVALID$'):
                self.attempt(result_change=lambda r: r.update({field: value}))

    def test_complete_review_checklist_is_required(self):
        for value in (None, [], CHECKS[:-1], CHECKS+[CHECKS[0]], CHECKS+[{}], 'approved'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^RESULT_SCOPE_INVALID$'):
                self.attempt(result_change=lambda r: r.update(remaining_checks=value))
        with self.assertRaisesRegex(ValueError, '^RESULT_SCOPE_INVALID$'):
            self.attempt(result_change=lambda r: r.pop('remaining_checks'))

    def test_manifest_scope_rejected_even_after_valid_rehash(self):
        for field, value in (('schema_version', True), ('schema_version', 1.0),
                            ('schema_version', 2), ('platform', 'redbubble'), ('platform', 'etsy'),
                            ('publication_enabled', True), ('publication_enabled', 0)):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, '^MANIFEST_SCOPE_INVALID$'):
                self.attempt(manifest_change=lambda m: m.update({field: value}))
        for field in ('schema_version', 'platform', 'publication_enabled'):
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, '^MANIFEST_SCOPE_INVALID$'):
                self.attempt(manifest_change=lambda m: m.pop(field))

    def test_empty_manifest_cannot_create_receipt(self):
        with self.assertRaisesRegex(ValueError, '^ARTIFACT_BATCH_INVALID$'):
            self.attempt(empty=True)


if __name__ == '__main__': unittest.main()
