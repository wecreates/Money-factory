"""Editorial evidence validation does not imply factual or creative approval."""
import copy
import unittest

from integrations.content_control.cycle_editorial import compile_editorial


def brief():
    return {'schema_version': 1, 'title': 'A fictional fee example', 'topic': 'Card fees',
            'sources': [{'id': 'source1', 'url': 'https://example.org/fees',
                         'retrieved_at': '2026-01-01T08:00:00-08:00',
                         'claim': 'Cards may charge annual fees.', 'excerpt': 'Some cards charge annual fees.'}],
            'reference_observations': [{'url': 'https://example.org/reference',
                                        'observed_at': '2026-01-02T00:00:00Z',
                                        'observation_type': 'transcript',
                                        'patterns': ['Start with a concrete question.']}],
            'scenes': [{'id': 's1', 'narration': 'Dave wonders whether the annual fee is worthwhile.',
                        'visual': 'Dave looks at a fictional card statement.', 'source_ids': ['source1'],
                        'duration_seconds': 6},
                       {'id': 's2', 'narration': 'My wallet wants a meeting.', 'visual': 'A wallet rings a bell.',
                        'source_ids': [], 'factual': False, 'duration_seconds': 3}]}


class EditorialTests(unittest.TestCase):
    def test_compile_preserves_content_provenance_without_approval(self):
        source = brief()
        before = copy.deepcopy(source)
        result = compile_editorial(source)
        self.assertEqual(source, before)
        self.assertEqual(result, compile_editorial(source))
        self.assertEqual(result['sources'][0]['retrieved_at'], '2026-01-01T16:00:00+00:00')
        self.assertEqual(result['scenes'][1]['start_seconds'], 6)
        self.assertEqual(result['planned_duration_seconds'], 9)
        self.assertEqual(result['reference_scope'], ['transcript'])
        self.assertFalse(result['reference_audiovisual_comparison_complete'])
        self.assertFalse(result['independent_fact_check_complete'])
        self.assertFalse(result['production_approved'])
        self.assertFalse(result['publication_enabled'])

    def test_changes_to_research_or_script_change_binding(self):
        first = compile_editorial(brief())['editorial_sha256']
        for field in ('narration', 'visual'):
            data = brief(); data['scenes'][0][field] += ' Updated.'
            self.assertNotEqual(first, compile_editorial(data)['editorial_sha256'])
        data = brief(); data['sources'][0]['excerpt'] += ' Updated.'
        self.assertNotEqual(first, compile_editorial(data)['editorial_sha256'])

    def test_optional_thumbnail_copy_preserves_legacy_identity_and_binds_new_copy(self):
        original = compile_editorial(brief())
        self.assertNotIn('thumbnail_copy', original)
        self.assertEqual(original['editorial_sha256'],
                         '5b92fc9051c46f4e920876ba278ca35458514fba51c864ad16ca6ef626f9d541')
        revised = compile_editorial(dict(brief(), thumbnail_copy='  Two  Totals? '))
        self.assertEqual(revised['thumbnail_copy'], 'Two Totals?')
        self.assertEqual(revised['title'], original['title'])
        self.assertEqual(revised['scenes'], original['scenes'])
        self.assertNotEqual(revised['editorial_sha256'], original['editorial_sha256'])

    def test_explicit_scene_gesture_is_bound_and_validated(self):
        subject = brief()
        spec = {'kind': 'comparison', 'headline': 'COMPARE TOTALS'}
        subject['scenes'][0]['visual_spec'] = spec
        original = compile_editorial(subject)
        for gesture in ('point_left', 'point_right', 'open_hands'):
            spec['gesture'] = gesture
            compiled = compile_editorial(subject)
            self.assertEqual(compiled['scenes'][0]['visual_spec']['gesture'], gesture)
            self.assertNotEqual(compiled['editorial_sha256'], original['editorial_sha256'])
        for unsupported in ('spin', [], None, True):
            spec['gesture'] = unsupported
            with self.assertRaisesRegex(ValueError, 'Gesture must'):
                compile_editorial(subject)

    def test_above_speaker_label_is_portrait_only_and_bound(self):
        base = compile_editorial(brief())
        revised = compile_editorial(dict(brief(), speaker_label_position='above'))
        self.assertEqual(revised['speaker_label_position'], 'above')
        self.assertNotEqual(base['editorial_sha256'], revised['editorial_sha256'])
        for extras in ({'speaker_label_position': 'below'}, {'speaker_label_position': None},
                       {'speaker_label_position': 'above', 'layout': 'landscape'}):
            with self.assertRaisesRegex(ValueError, 'speaker_label_position'):
                compile_editorial(dict(brief(), **extras))

    def test_thumbnail_copy_rejects_multiline_controls_and_oversize(self):
        for value in (None, 3, '', '  ', 'One\nTwo', 'One\tTwo', 'One\u202eTwo', 'a' * 49):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'thumbnail_copy'):
                compile_editorial(dict(brief(), thumbnail_copy=value))

    def test_factual_scene_cannot_have_missing_unknown_or_duplicate_citations(self):
        for citations in ([], ['missing'], ['source1', 'source1'], [None]):
            with self.subTest(citations=citations), self.assertRaises(ValueError):
                data = brief(); data['scenes'][0]['source_ids'] = citations
                compile_editorial(data)

    def test_source_and_scene_ids_are_unique_and_path_safe(self):
        for collection in ('sources', 'scenes'):
            data = brief(); data[collection].append(copy.deepcopy(data[collection][0]))
            with self.assertRaisesRegex(ValueError, 'duplicate'): compile_editorial(data)
            data = brief(); data[collection][0]['id'] = '../outside'
            with self.assertRaisesRegex(ValueError, 'identifier'): compile_editorial(data)

    def test_evidence_requires_timezone_and_cannot_be_future(self):
        for stamp in ('2026-01-01', 'not-a-date', '2099-01-01T00:00:00Z'):
            data = brief(); data['sources'][0]['retrieved_at'] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ValueError): compile_editorial(data)

    def test_nonfinite_or_boolean_durations_rejected(self):
        for duration in (float('nan'), float('inf'), True, 0, 61, '6'):
            data = brief(); data['scenes'][0]['duration_seconds'] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError): compile_editorial(data)

    def test_missing_research_or_reference_rejected(self):
        for field in ('sources', 'reference_observations', 'scenes'):
            data = brief(); data[field] = []
            with self.assertRaises(ValueError): compile_editorial(data)

    def test_nested_publication_or_paid_flags_cannot_be_enabled_or_truthy(self):
        for field in ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review',
                      'factual_review', 'production_ready', 'competitor_comparison'):
            for value in (True, 'false', 0, None):
                data = brief(); data['scenes'][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError): compile_editorial(data)

    def test_invalid_urls_and_credentials_rejected(self):
        for url in ('file:///tmp/a', 'http://example.org', 'https://u:p@example.org',
                    'https://example.org:bad', 'https://exa mple.org'):
            data = brief(); data['sources'][0]['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError): compile_editorial(data)

    def test_observation_type_does_not_upgrade_evidence(self):
        data = brief(); data['reference_observations'][0]['observation_type'] = 'audiovisual'
        result = compile_editorial(data)
        self.assertEqual(result['reference_scope'], ['audiovisual'])
        self.assertFalse(result['reference_audiovisual_comparison_complete'])
        data['reference_observations'][0]['observation_type'] = 'watched-most-likely'
        with self.assertRaises(ValueError): compile_editorial(data)

    def test_visual_spec_is_validated_and_preserved(self):
        data = brief()
        spec = {'kind': 'comparison', 'headline': 'Compare the cost',
                'labels': ['Annual fee', 'Value used'], 'values': ['$100', '$70']}
        data['scenes'][0]['visual_spec'] = spec
        self.assertEqual(compile_editorial(data)['scenes'][0]['visual_spec'], spec)
        spec['labels'] = ['a'] * 5
        with self.assertRaises(ValueError): compile_editorial(data)
        spec['labels'] = ['a']; spec['kind'] = 'shell-command'
        with self.assertRaises(ValueError): compile_editorial(data)

    def test_unknown_voice_does_not_change_character_assignment(self):
        data = brief(); data['scenes'][0]['speaker'] = 'another-voice'
        with self.assertRaisesRegex(ValueError, 'speaker'): compile_editorial(data)

    def test_renderer_limits_rejected_before_compilation(self):
        for field in ('narration', 'visual'):
            data = brief(); data['scenes'][0][field] = 'a' * 1001
            with self.assertRaises(ValueError): compile_editorial(data)
        data = brief(); data['scenes'] = [dict(data['scenes'][0], id=f's{i}') for i in range(31)]
        with self.assertRaises(ValueError): compile_editorial(data)
        data = brief(); data['scenes'] = [dict(data['scenes'][0], id=f's{i}', duration_seconds=60) for i in range(11)]
        with self.assertRaisesRegex(ValueError, '600'): compile_editorial(data)


if __name__ == '__main__':
    unittest.main()
