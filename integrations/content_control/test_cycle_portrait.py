"""Synthetic handoff fixtures cover source selection and binding."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.cycle_portrait import prepare_portrait
from integrations.content_control.review_package import digest
from integrations.content_control.test_cycle_editorial import brief as sample_brief


class PortraitTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'parent'
        self.output = self.root.with_name('child')
        (self.root / 'delivery').mkdir(parents=True)
        self.source = sample_brief()
        self.source['layout'] = 'landscape'
        self.source['scenes'] = [dict(self.source['scenes'][0], id=key) for key in ('one', 'two', 'three')]
        self.render = {'layout': 'landscape', 'scenes': [{'scene_id': key, 'start': n * 3, 'end': (n + 1) * 3}
                                                        for n, key in enumerate(('one', 'two', 'three'))]}
        self.inspect = self.enterContext(patch('integrations.content_control.cycle_portrait.inspect_cycle'))
        self.enterContext(patch('integrations.content_control.cycle_portrait.inspect_media', return_value={'duration_seconds': 9}))
        self.write_parent()

    def write_parent(self):
        (self.root / 'brief.json').write_text(json.dumps(self.source))
        (self.root / 'delivery/render.json').write_text(json.dumps(self.render))
        self.inspect.return_value = {'editorial': compile_editorial(self.source), 'candidate_sha256': 'a' * 64,
                                     'files_sha256': {'cycle.json': 'b' * 64, 'delivery/package.json': 'c' * 64,
                                         **{name: digest(self.root / name) for name in ('delivery/render.json', 'brief.json')}}}

    def test_exact_scenes_and_sources_retained_in_new_portrait_brief(self):
        result = prepare_portrait(self.root, self.output, scene_ids=['two', 'three'], title='Short title')
        b = json.loads((self.output / 'brief.json').read_text())
        self.assertNotIn('layout', b)
        self.assertEqual(b['scenes'], self.source['scenes'][1:])
        self.assertEqual(b['sources'], self.source['sources'])
        self.assertEqual(b['reference_observations'], self.source['reference_observations'])
        self.assertEqual(b['portrait_handoff'], result['parent'])
        self.assertEqual(result['parent']['scenes'][0], {'scene_id': 'two', 'start_seconds': 3, 'end_seconds': 6})
        self.assertEqual(result['brief_sha256'], digest(self.output / 'brief.json'))
        self.assertEqual(b['title'], 'Short title')
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['production_approved'])

    def test_rejects_unknown_duplicate_reversed_and_noncontiguous_selections(self):
        for ids in (['absent'], ['one', 'one'], ['two', 'one'], ['one', 'three']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                prepare_portrait(self.root, self.output, scene_ids=ids)
            self.assertFalse(self.output.exists())

    def test_rejects_header_only_or_over_budget_briefs(self):
        del self.source['layout']
        del self.render['layout']
        self.write_parent()
        with self.assertRaisesRegex(ValueError, 'Native landscape'):
            prepare_portrait(self.root, self.output, scene_ids=['one'])
        self.source['layout'] = self.render['layout'] = 'landscape'
        for scene in self.source['scenes']:
            scene['duration_seconds'] = 31
        self.write_parent()
        with self.assertRaisesRegex(ValueError, 'planning duration'):
            prepare_portrait(self.root, self.output, scene_ids=['one', 'two'])
        self.assertFalse(self.output.exists())
