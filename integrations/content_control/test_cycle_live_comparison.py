"""Schema fixtures test comparison binding, not actual playback or creative quality."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_live_comparison import (
    record_live_comparison, validate_observations, validate_recorded_comparison,
    verify_live_comparison,
)


SHA = 'a' * 64


def intervals(duration):
    split = min(4, duration)
    points = [(0, split)] if split == duration else [(0, split), (split, duration)]
    return [{
        'start_seconds': start, 'end_seconds': end,
        'audio_observation': 'Voice, music and effects were heard throughout this interval.',
        'visual_observation': 'Composition, motion and readable text were watched throughout this interval.',
        'pacing_observation': 'Cut timing and information density were observed for this interval.',
        'story_observation': 'Setup, development and payoff contribution were recorded for this interval.',
    } for start, end in points]


def packet():
    access = {'mode': 'live_view_only', 'playback_permitted': True,
              'media_downloaded': False, 'accessible': True,
              'picture_accessible': True, 'sound_accessible': True}
    common = {'topic': 'Minimum payment credit-card explainer', 'format': 'portrait',
              'selection_basis': 'Relevant high-performing finance explainer in the same topic and vertical format.',
              'selected_at': '2026-11-24T09:30:00Z',
              'observed_at': '2026-11-24T10:00:00Z', 'access': access,
              'candidate_differences': {
                  'audio': 'The reference uses a denser music bed than the candidate.',
                  'visual': 'The reference changes visual focus more often than the candidate.',
                  'pacing': 'The reference reaches its first concrete example sooner.',
                  'story': 'The reference states the viewer consequence before the explanation.',
              },
              'actionable_findings': [
                  'Test an earlier consequence card without changing the sourced claim.',
              ]}
    return {
        'schema_version': 2, 'candidate_sha256': SHA,
        'reviewer': 'Playback review operator', 'reviewed_at': '2026-11-24T10:30:00Z',
        'candidate_observation': {'duration_seconds': 10, 'intervals': intervals(10)},
        'references': [
            {**copy.deepcopy(common), 'url': 'https://www.instagram.com/reel/DgAHyVPhMi0/',
             'selection_evidence_url': 'https://rank.example.com/finance/first',
             'duration_seconds': 12, 'intervals': intervals(12)},
            {**copy.deepcopy(common), 'url': 'https://www.youtube.com/watch?v=DHjqpvDnNGE',
             'selection_evidence_url': 'https://rank.example.com/finance/second',
             'duration_seconds': 15, 'intervals': intervals(15)},
        ],
    }


class LiveComparisonTests(unittest.TestCase):
    def test_two_full_live_view_observations_are_bound_without_approval(self):
        value = packet()
        normalized = validate_observations(value, SHA)
        self.assertEqual(normalized['candidate_sha256'], SHA)
        self.assertEqual(len(normalized['references']), 2)
        self.assertEqual(normalized['references'][0]['access']['mode'], 'live_view_only')
        self.assertEqual(normalized['candidate_observation']['intervals'][-1]['end_seconds'], 10)
        self.assertEqual(set(normalized['references'][0]['candidate_differences']),
                         {'audio', 'visual', 'pacing', 'story'})
        self.assertEqual(len(normalized['references'][0]['actionable_findings']), 1)

    def test_records_exact_candidate_and_source_hash_without_mutating_cycle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cycle = root / 'cycle'; cycle.mkdir()
            (cycle / 'delivery').mkdir()
            (cycle / 'delivery/render.json').write_text(json.dumps({'duration_seconds': 10}))
            source = root / 'observations.json'; output = root / 'outside' / 'comparison.json'
            source.write_text(json.dumps(packet()))
            snapshot = {'candidate_sha256': SHA,
                        'cycle': {'finished_at': '2026-11-24T09:00:00+00:00'},
                        'editorial': {'topic': 'Minimum payment credit-card explainer'},
                        'files_sha256': {'cycle.json': 'b' * 64}}
            with patch('integrations.content_control.cycle_live_comparison.inspect_cycle',
                       side_effect=[copy.deepcopy(snapshot), copy.deepcopy(snapshot)]):
                result = record_live_comparison(cycle, source, output)
            self.assertEqual(result, json.loads(output.read_text()))
            self.assertEqual(result['status'], 'COMPARISON_ATTESTATION_RECORDED')
            self.assertTrue(result['full_interval_schema_validated'])
            self.assertRegex(result['normalized_observations_sha256'], r'^[a-f0-9]{64}$')
            for field in ('independent_verification', 'competitor_comparison_verified',
                          'full_av_review', 'production_approved', 'production_ready',
                          'publication_enabled', 'paid_generation_enabled'):
                self.assertIs(result[field], False)

    def test_replays_retained_source_and_receipt_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cycle = root / 'cycle'; cycle.mkdir()
            (cycle / 'delivery').mkdir()
            (cycle / 'delivery/render.json').write_text(json.dumps({'duration_seconds': 10}))
            source = root / 'observations.json'; receipt = root / 'outside' / 'comparison.json'
            source.write_text(json.dumps(packet()))
            snapshot = {'candidate_sha256': SHA,
                        'cycle': {'finished_at': '2026-11-24T09:00:00+00:00'},
                        'editorial': {'topic': 'Minimum payment credit-card explainer'},
                        'files_sha256': {'cycle.json': 'b' * 64}}
            with patch('integrations.content_control.cycle_live_comparison.inspect_cycle',
                       return_value=copy.deepcopy(snapshot)):
                recorded = record_live_comparison(cycle, source, receipt)
                replayed, receipt_sha = verify_live_comparison(cycle, source, receipt)
                self.assertEqual(recorded, replayed)
                self.assertRegex(receipt_sha, r'^[a-f0-9]{64}$')

                changed = copy.deepcopy(recorded)
                changed['references'][0]['candidate_differences']['audio'] = (
                    'A changed statement must not retain the old comparison identity.')
                with self.assertRaisesRegex(ValueError, 'identity, evidence or scope changed'):
                    validate_recorded_comparison(cycle, changed)

                future = copy.deepcopy(recorded)
                future['recorded_at'] = '2999-01-01T00:00:00+00:00'
                with self.assertRaisesRegex(ValueError, 'future'):
                    validate_recorded_comparison(cycle, future)

    def test_rejects_missing_inaccessible_downloaded_duplicate_or_unranked_references(self):
        cases = []
        one = packet(); one['references'].pop(); cases.append(one)
        duplicate = packet(); duplicate['references'][1]['url'] = duplicate['references'][0]['url']; cases.append(duplicate)
        youtube_playback_alias = packet()
        youtube_playback_alias['references'][0]['url'] = 'https://youtu.be/DHjqpvDnNGE'
        cases.append(youtube_playback_alias)
        instagram_playback_alias = packet()
        instagram_playback_alias['references'][1]['url'] = (
            'https://m.instagram.com/reels/DgAHyVPhMi0/')
        cases.append(instagram_playback_alias)
        query_alias = packet()
        query_alias['references'][0]['url'] = 'https://www.player.example.com/video/?id=1&x=2'
        query_alias['references'][1]['url'] = 'https://player.example.com/video?x=2&id=1'
        cases.append(query_alias)
        unranked = packet(); unranked['references'][0]['selection_evidence_url'] = unranked['references'][0]['url']; cases.append(unranked)
        unranked_alias = packet()
        unranked_alias['references'][0]['selection_evidence_url'] = 'https://instagram.com/reel/DgAHyVPhMi0'
        cases.append(unranked_alias)
        mobile_alias = packet()
        mobile_alias['references'][0]['selection_evidence_url'] = 'https://m.instagram.com/reels/DgAHyVPhMi0/'
        cases.append(mobile_alias)
        cross_playback = packet()
        cross_playback['references'][0]['selection_evidence_url'] = 'https://youtube.com/watch?v=DHjqpvDnNGE'
        cases.append(cross_playback)
        youtube_alias = packet()
        youtube_alias['references'][0]['selection_evidence_url'] = 'https://youtu.be/DHjqpvDnNGE'
        cases.append(youtube_alias)
        same_rank = packet(); same_rank['references'][1]['selection_evidence_url'] = same_rank['references'][0]['selection_evidence_url']; cases.append(same_rank)
        rank_alias = packet()
        rank_alias['references'][0]['selection_evidence_url'] = 'https://www.rank.example.com/list/?topic=finance&day=today'
        rank_alias['references'][1]['selection_evidence_url'] = 'https://rank.example.com/list?day=today&topic=finance'
        cases.append(rank_alias)
        rank_media_alias = packet()
        rank_media_alias['references'][0]['selection_evidence_url'] = 'https://www.youtube.com/watch?v=abcdefghijk'
        rank_media_alias['references'][1]['selection_evidence_url'] = 'https://youtu.be/abcdefghijk'
        cases.append(rank_media_alias)
        for field, value in [('playback_permitted', False), ('media_downloaded', True),
                             ('accessible', False), ('picture_accessible', False),
                             ('sound_accessible', False)]:
            changed = packet(); changed['references'][0]['access'][field] = value; cases.append(changed)
        for value in cases:
            with self.subTest(references=len(value['references'])):
                with self.assertRaises(ValueError):
                    validate_observations(value, SHA)

    def test_rejects_partial_or_non_audiovisual_interval_coverage(self):
        cases = []
        gap = packet(); gap['references'][0]['intervals'][1]['start_seconds'] = 5; cases.append(gap)
        short = packet(); short['candidate_observation']['intervals'].pop(); cases.append(short)
        overlap = packet(); overlap['references'][1]['intervals'][1]['start_seconds'] = 3; cases.append(overlap)
        for field in ('audio_observation', 'visual_observation', 'pacing_observation', 'story_observation'):
            missing = packet(); missing['references'][0]['intervals'][0][field] = ''; cases.append(missing)
        for value in cases:
            with self.assertRaises(ValueError):
                validate_observations(value, SHA)

    def test_recording_fails_closed_when_publication_or_paid_generation_is_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cycle = root / 'cycle'; cycle.mkdir()
            (cycle / 'delivery').mkdir()
            (cycle / 'delivery/render.json').write_text(json.dumps({'duration_seconds': 10}))
            source = root / 'observations.json'; source.write_text(json.dumps(packet()))
            snapshot = {'candidate_sha256': SHA,
                        'cycle': {'finished_at': '2026-11-24T09:00:00+00:00'},
                        'editorial': {'topic': 'Minimum payment credit-card explainer'},
                        'files_sha256': {'cycle.json': 'b' * 64}}
            for index, name in enumerate(('PUBLICATION_ENABLED',
                                          'PAID_GENERATION_ENABLED')):
                with self.subTest(name=name), \
                     patch.dict('os.environ', {name: 'true'}, clear=False), \
                     patch('integrations.content_control.cycle_live_comparison.inspect_cycle',
                           return_value=copy.deepcopy(snapshot)), \
                     self.assertRaisesRegex(ValueError, 'must remain disabled'):
                    record_live_comparison(
                        cycle, source, root / f'outside-{index}' / 'comparison.json')

    def test_rejects_observations_without_explicit_differences_or_actions(self):
        cases = []
        missing_differences = packet()
        missing_differences['references'][0].pop('candidate_differences')
        cases.append(missing_differences)
        partial_differences = packet()
        partial_differences['references'][0]['candidate_differences'].pop('audio')
        cases.append(partial_differences)
        blank_difference = packet()
        blank_difference['references'][0]['candidate_differences']['story'] = ''
        cases.append(blank_difference)
        no_findings = packet()
        no_findings['references'][0]['actionable_findings'] = []
        cases.append(no_findings)
        vague_finding = packet()
        vague_finding['references'][0]['actionable_findings'] = ['fix it']
        cases.append(vague_finding)
        for value in cases:
            with self.assertRaises(ValueError):
                validate_observations(value, SHA)

        legacy = packet()
        legacy['schema_version'] = 1
        with self.assertRaisesRegex(ValueError, 'schema version 2'):
            validate_observations(legacy, SHA)

    def test_rejects_wrong_candidate_nonspecific_links_and_time_reversal(self):
        with self.assertRaisesRegex(ValueError, 'different candidate'):
            validate_observations(packet(), 'b' * 64)
        for url in ('https://www.instagram.com/oddsofmind/',
                    'https://www.youtube.com/watch?v=short',
                    'https://127.0.0.1/video'):
            changed = packet(); changed['references'][0]['url'] = url
            with self.assertRaises(ValueError):
                validate_observations(changed, SHA)
        changed = packet(); changed['references'][0]['observed_at'] = '2026-11-24T08:00:00Z'
        with self.assertRaisesRegex(ValueError, 'cannot predate'):
            validate_observations(changed, SHA)
        changed = packet(); changed['reviewed_at'] = '2026-11-24T09:45:00Z'
        with self.assertRaisesRegex(ValueError, 'cannot predate reference playback'):
            validate_observations(changed, SHA)

    def test_cycle_binding_rejects_different_topic_or_format(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cycle = root / 'cycle'; cycle.mkdir()
            (cycle / 'delivery').mkdir()
            (cycle / 'delivery/render.json').write_text(json.dumps({'duration_seconds': 10}))
            source = root / 'observations.json'
            snapshot = {'candidate_sha256': SHA,
                        'cycle': {'finished_at': '2026-11-24T09:00:00+00:00'},
                        'editorial': {'topic': 'Minimum payment credit-card explainer'},
                        'files_sha256': {'cycle.json': 'b' * 64}}
            for field, value in [('topic', 'Unrelated mortgage topic'), ('format', 'landscape')]:
                changed = packet(); changed['references'][0][field] = value
                source.write_text(json.dumps(changed))
                with self.subTest(field=field), \
                     patch('integrations.content_control.cycle_live_comparison.inspect_cycle',
                           return_value=copy.deepcopy(snapshot)), \
                     self.assertRaisesRegex(ValueError, field):
                    record_live_comparison(cycle, source, root / f'{field}.json')
            changed = packet()
            changed['candidate_observation'] = {'duration_seconds': 9, 'intervals': intervals(9)}
            source.write_text(json.dumps(changed))
            with patch('integrations.content_control.cycle_live_comparison.inspect_cycle',
                       return_value=copy.deepcopy(snapshot)), \
                 self.assertRaisesRegex(ValueError, 'encoded candidate duration'):
                record_live_comparison(cycle, source, root / 'duration.json')


if __name__ == '__main__':
    unittest.main()
