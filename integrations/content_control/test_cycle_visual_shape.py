"""Reject silent visual omissions before production; retain historical identities."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import complete_cycle, cycle_render
from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.test_cycle_editorial import brief


INVALID = [
    {'kind':'balance', 'labels':['ONE','TWO','THREE'], 'values':[]},
    {'kind':'balance', 'labels':[], 'values':['ONE','TWO','THREE']},
    {'kind':'balance', 'labels':['MEANING'], 'values':['AMOUNT']},
    {'kind':'checklist', 'labels':['MEANING'], 'values':['AMOUNT']},
    {'kind':'comparison', 'labels':['ONE','TWO','THREE'], 'values':[]},
    {'kind':'comparison', 'labels':[], 'values':['ONE','TWO','THREE']},
]


class VisualShapeTests(unittest.TestCase):
    def source(self, shape):
        value = brief()
        value['scenes'][0]['visual_spec'] = dict(shape, headline='Preserve every field')
        return value

    def test_invalid_shapes_reject_before_voice_or_output(self):
        for shape in INVALID:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as td:
                root=Path(td); source=root/'brief.json'; source.write_text(json.dumps(self.source(shape)))
                with patch.object(complete_cycle, 'render_cycle') as render, self.assertRaises(ValueError):
                    complete_cycle.run_cycle(source,root/'cycle',voice_python=sys.executable,voice_root=td)
                render.assert_not_called(); self.assertFalse((root/'cycle').exists())
                historical=compile_editorial(self.source(shape))
                with patch.object(cycle_render, 'run') as run, self.assertRaises(ValueError):
                    cycle_render.render_cycle(historical,root/'render',voice_python=sys.executable,voice_root=td)
                run.assert_not_called(); self.assertFalse((root/'render').exists())

    def test_direct_panel_does_not_silently_drop_fields(self):
        for shape in INVALID + [{'kind':'checklist','labels':['A']*5,'values':[]}]:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as td:
                path=Path(td)/'panel.png'; scene=self.source(shape)['scenes'][0]
                with self.assertRaises(ValueError): cycle_render.draw_panel(scene,path,0,2)
                self.assertFalse(path.exists())

    def test_malformed_direct_specs_fail_before_output(self):
        specs=[None, [], {'kind':'unknown'}, {'kind':'balance','labels':None},
               {'kind':'balance','labels':'AB'}, {'kind':'card','values':[42]}]
        for spec in specs:
            with tempfile.TemporaryDirectory() as td:
                scene=brief()['scenes'][0]; scene['visual_spec']=spec
                path=Path(td)/'panel.png'
                with self.assertRaises(ValueError): cycle_render.draw_panel(scene,path,0,2)
                self.assertFalse(path.exists())

    def test_supported_shapes_preserve_normalization_and_input(self):
        shapes=[{'kind':kind,'labels':['A','B'],'values':['1','2']}
                for kind in ('card','receipt','comparison')]
        shapes += [{'kind':kind,'labels':['A','B'],'values':[]} for kind in ('balance','checklist')]
        shapes += [{'kind':kind,'labels':[],'values':['1','2']} for kind in ('balance','checklist')]
        for shape in shapes:
            source=self.source(shape); before=copy.deepcopy(source)
            self.assertEqual(compile_editorial(source,validate_visual_shapes=True),compile_editorial(source))
            self.assertEqual(source,before)
            cycle_render.validate(compile_editorial(source))

    def test_explicit_reveal_is_bound_and_rejects_ambiguous_inputs(self):
        shape = {'kind':'comparison','labels':['PENDING','POSTED'],'values':['20','24']}
        source = self.source(dict(shape, reveal_after_seconds=4.3))
        compiled = compile_editorial(source, validate_visual_shapes=True)
        self.assertEqual(compiled['scenes'][0]['visual_spec']['reveal_after_seconds'], 4.3)
        self.assertNotEqual(compiled['editorial_sha256'], compile_editorial(self.source(shape))['editorial_sha256'])
        for offset in (True, None, '4.3', float('inf'), float('nan'), 0, 60):
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError,'reveal offset'):
                compile_editorial(self.source(dict(shape, reveal_after_seconds=offset)))
        for invalid in (dict(shape,kind='card'), dict(shape,values=['20'])):
            with self.assertRaisesRegex(ValueError,'two complete comparison cards'):
                compile_editorial(self.source(dict(invalid, reveal_after_seconds=1)))
        half_second = compile_editorial(self.source(dict(shape,reveal_after_seconds=.29)))['scenes'][0]
        self.assertEqual(cycle_render.picture_filters(half_second,19)[1]['first_visible_scene_frame'],7)
        with self.assertRaisesRegex(ValueError,'half a second'):
            cycle_render.picture_filters(half_second,18)

    def test_landscape_layout_is_explicit_and_bound(self):
        source = brief()
        prior = compile_editorial(source)
        self.assertNotIn('layout', prior)
        current = compile_editorial(dict(source, layout='landscape'), validate_visual_shapes=True)
        self.assertEqual(current['layout'], 'landscape')
        self.assertEqual(current['scenes'], prior['scenes'])
        self.assertNotEqual(current['editorial_sha256'], prior['editorial_sha256'])
        for value in (None, True, 'portrait', 'landscape ', '16:9', [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'layout'):
                    compile_editorial(dict(source, layout=value))
                with self.assertRaisesRegex(ValueError, 'layout'):
                    cycle_render.validate(dict(prior, layout=value))

    def test_existing_brief_historical_hashes_unchanged(self):
        # Captured from main096c233 before the production-only validation change.
        expected={'minimum-payment-brief.json':'c4d7805291b67ef162c087511fd5d6caba601a7a877d0247585033d3603de908',
                  'rewards-card-brief.json':'775b87ae1d4b925bdcfd69d246bf781cb6d104c211bbf8e338ab5fbab6e85577',
                  'statement-balance-brief.json':'38c92ad7622b925840030d3d99b8c7288d9ea1ae51ca3c41d4ec43ec65ec32bb'}
        for name, sha in expected.items():
            source=json.loads((Path(__file__).parent/'examples'/name).read_text())
            actual=hashlib.sha256(json.dumps(compile_editorial(source),sort_keys=True).encode()).hexdigest()
            self.assertEqual(actual,sha)
            if name=='rewards-card-brief.json':
                with self.assertRaisesRegex(ValueError,'paired fields'):
                    compile_editorial(source,validate_visual_shapes=True)
            else:
                self.assertEqual(compile_editorial(source,validate_visual_shapes=True),compile_editorial(source))


if __name__=='__main__': unittest.main()
