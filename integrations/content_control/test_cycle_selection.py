"""Synthetic packet acceptance checks, not real audience or creative evidence."""
import copy
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_selection import (
    _read_selection, _selection_result, record_selection, verify_selection,
)
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control import test_cycle_review as fixtures

write = fixtures.write


class SelectionTests(unittest.TestCase):
    setUp = fixtures.ReviewTests.setUp
    tearDown = fixtures.ReviewTests.tearDown

    def selection(self):
        snapshot = inspect_cycle(self.root)
        return {'schema_version': 2, 'candidate_sha256': self.candidate,
                'package_sha256': snapshot['files_sha256']['delivery/package.json'],
                'thumbnail': 'thumbnail-2.png',
                'thumbnail_sha256': snapshot['files_sha256']['delivery/thumbnail-2.png'],
                'title': snapshot['editorial']['title'], 'reviewer': 'Fixture reviewer',
                'reviewed_at': '2026-01-04T00:00:00Z',
                'rationale': 'Synthetic selection rationale, not a visual observation.',
                'next_idea_hypotheses': ['Test simpler wording in the next unpublished candidate.']}

    def record(self, selection):
        write(self.submitted, selection)
        return record_selection(self.root, self.submitted, self.recorded)

    def test_unavailable_metrics_stay_unknown_and_cycle_unchanged(self):
        before = inspect_cycle(self.root)
        result = self.record(self.selection())
        self.assertEqual(result['performance']['status'], 'UNAVAILABLE')
        self.assertIsNone(result['performance']['ctr'])
        self.assertIsNone(result['performance']['impressions'])
        self.assertFalse(result['production_approved'])
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['independent_verification'])
        self.assertNotIn('thumbnail_copy', result)
        self.assertEqual(inspect_cycle(self.root), before)

    def test_stale_identity_title_and_timestamp_rejected(self):
        for key, value in [('candidate_sha256','0'*64), ('package_sha256','0'*64),
                           ('thumbnail_sha256','0'*64), ('thumbnail','../../file'),
                           ('title','Different title'), ('thumbnail_copy','Different copy'),
                           ('reviewed_at','2026-01-01T00:00:00Z')]:
            with self.subTest(key=key):
                selection = self.selection(); selection[key] = value
                with self.assertRaises(ValueError): self.record(selection)
                self.assertFalse(self.recorded.exists())

    def test_independent_thumbnail_copy_does_not_relabel_selected_title(self):
        selection = self.selection()
        snapshot = inspect_cycle(self.root)
        snapshot['editorial']['thumbnail_copy'] = 'Two Totals?'
        with patch('integrations.content_control.cycle_selection.inspect_cycle', return_value=snapshot):
            wrong_title = dict(selection, title='Two Totals?')
            with self.assertRaisesRegex(ValueError, 'Title must match'):
                self.record(wrong_title)
            result = self.record(dict(selection, thumbnail_copy='Two Totals?'))
        self.assertEqual(result['title'], selection['title'])
        self.assertEqual(result['thumbnail_copy'], 'Two Totals?')

    def performance(self, selection, impressions=100, clicks=5):
        return dict(candidate_sha256=self.candidate, package_sha256=selection['package_sha256'],
                    thumbnail=selection['thumbnail'],
                    thumbnail_sha256=selection['thumbnail_sha256'],
                    title=selection['title'], impressions=impressions, clicks=clicks,
                    window_start='2026-01-04T00:00:00Z', window_end='2026-01-05T00:00:00Z',
                    observed_at='2026-01-06T00:00:00Z', source_url='https://example.com/analytics',
                    evidence='Synthetic analytics fixture; not actual audience evidence.')

    def test_supplied_metrics_never_become_verified(self):
        selection = self.selection(); selection['performance'] = self.performance(selection)
        result = self.record(selection)
        self.assertEqual(result['performance']['ctr'], 0.05)
        self.assertEqual(result['performance']['status'], 'SUPPLIED_UNVERIFIED')
        self.assertFalse(result['performance']['independently_verified'])

    def test_performance_schema_rejects_fabricated_ctr_and_audience_claims(self):
        selection = self.selection()
        supplied = self.performance(selection)
        for key, value in (
                ('ctr', 0.99),
                ('audience_performance_verified', True),
                ('winner_inferred', True),
                ('independently_verified', True),
                ('status', 'VERIFIED')):
            trial = copy.deepcopy(selection)
            trial['performance'] = dict(supplied, **{key: value})
            with self.subTest(key=key), self.assertRaisesRegex(
                    ValueError, 'Exact supplied performance fields required'):
                self.record(trial)

    def test_performance_must_bind_exact_package(self):
        selection = self.selection()
        selection['performance'] = self.performance(selection)
        selection['performance']['package_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'candidate, package, title, and thumbnail'):
            self.record(selection)

    def test_performance_must_bind_exact_thumbnail_filename(self):
        selection = self.selection()
        selection['performance'] = self.performance(selection)
        selection['performance']['thumbnail'] = 'thumbnail-1.png'
        with self.assertRaisesRegex(ValueError, 'candidate, package, title, and thumbnail'):
            self.record(selection)

    def test_performance_window_cannot_predate_selection(self):
        selection = self.selection()
        selection['performance'] = self.performance(selection)
        selection['performance'].update(
            window_start='2026-01-03T00:00:00Z',
            window_end='2026-01-03T12:00:00Z',
            observed_at='2026-01-03T13:00:00Z')
        with self.assertRaisesRegex(ValueError, 'Performance predates selection'):
            self.record(selection)

    def test_outer_performance_claims_and_unknown_fields_are_rejected(self):
        for key, value in (('schema_version', 1), ('ctr', .99), ('status', 'VERIFIED'),
                           ('winner_inferred', True),
                           ('audience_performance_verified', True)):
            selection = self.selection()
            selection['performance'] = self.performance(selection)
            selection[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                    ValueError, 'Exact selection fields'):
                self.record(selection)

    def test_schema_one_performance_receipt_remains_replayable(self):
        selection = self.selection()
        selection.pop('schema_version')
        performance = self.performance(selection)
        performance.pop('package_sha256')
        performance.pop('thumbnail')
        selection['performance'] = performance
        write(self.submitted, selection)
        snapshot = inspect_cycle(self.root)
        source_hash = _read_selection(self.submitted)[1]
        receipt = _selection_result(
            snapshot, selection, source_hash, '2026-01-06T00:00:00+00:00',
            schema_version=1, legacy_replay=True)
        write(self.recorded, receipt)
        self.assertEqual(
            verify_selection(self.root, self.submitted, self.recorded)[0], receipt)

    def test_zero_impressions_has_no_ctr(self):
        selection = self.selection(); selection['performance'] = self.performance(selection, 0, 0)
        self.assertIsNone(self.record(selection)['performance']['ctr'])

    def test_historical_receipt_cannot_predate_its_performance_observation(self):
        selection = self.selection()
        selection['performance'] = self.performance(selection)
        receipt = self.record(selection)
        receipt['recorded_at'] = '2026-01-06T00:00:00+00:00'
        write(self.recorded, receipt)
        self.assertEqual(verify_selection(self.root, self.submitted, self.recorded)[0], receipt)
        receipt['recorded_at'] = '2026-01-05T12:00:00+00:00'
        write(self.recorded, receipt)
        with self.assertRaisesRegex(ValueError, 'Receipt predates performance observation'):
            verify_selection(self.root, self.submitted, self.recorded)

    def test_invalid_metrics_and_false_provenance_rejected(self):
        selection = self.selection(); selection['performance'] = self.performance(selection)
        for key, value in [('impressions',True), ('clicks',101), ('clicks',-1),
                           ('candidate_sha256','0'*64), ('thumbnail_sha256','0'*64),
                           ('source_url','https://user:secret@example.com'),
                           ('window_start','2026-01-07T00:00:00Z')]:
            trial = copy.deepcopy(selection); trial['performance'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.record(trial)
        selection['production_approved'] = True
        with self.assertRaises(ValueError): self.record(selection)

    def test_output_and_publication_guards(self):
        self.record(self.selection())
        original = self.recorded.read_bytes()
        with self.assertRaises(ValueError): self.record(self.selection())
        self.assertEqual(self.recorded.read_bytes(), original)
        with self.assertRaises(ValueError):
            record_selection(self.root, self.submitted, self.root/'selection.json')
        with patch.dict('os.environ', {'PUBLICATION_ENABLED':'true'}), self.assertRaises(ValueError):
            record_selection(self.root, self.submitted, self.base/'another.json')


if __name__ == '__main__':
    unittest.main()
