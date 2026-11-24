"""Offline original-draft authoring provenance and downstream replay tests."""
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.content_control.cycle_authoring import (
    ALGORITHM, LONG_FORM_ALGORITHM, LONG_FORM_FORMAT, LONG_FORM_MIN_SECONDS,
    author_draft,
)
from integrations.content_control.cycle_discovery import select_topic
from integrations.content_control.cycle_editorial import FALSE_FLAGS, compile_editorial
from integrations.content_control.cycle_intake import prepare_brief, verify_intake
from integrations.content_control.cycle_job import brief_digest, production_handoff
from integrations.content_control.complete_cycle import run_cycle
from integrations.content_control.test_cycle_discovery import iso, reference, source


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pool = self.root / 'pool.json'
        self.selected = self.root / 'selected'
        self.draft = self.root / 'draft.json'
        self.ready = self.root / 'ready'
        created = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        evidence = created - timedelta(days=1)
        self.pool.write_text(json.dumps({
            'schema_version': 1, 'created_at': iso(created), 'candidates': [
                {'id': 'fees', 'topic': 'How card fees change reward value',
                 'sources': [source('a', 'one.example', evidence),
                             source('b', 'two.example', evidence)],
                 'reference_observations': [reference(evidence, 'reference.example')]},
                {'id': 'minimums', 'topic': 'What a minimum payment does',
                 'sources': [source('c', 'one.example', evidence),
                             source('d', 'two.example', evidence),
                             source('e', 'three.example', evidence)],
                 'reference_observations': [reference(evidence, 'other-reference.example')]},
            ],
        }))
        select_topic(self.pool, self.selected)
        self.research = self.selected / 'research.json'
        self.discovery = self.selected / 'discovery.json'

    def author(self, content_format='standard'):
        return author_draft(self.pool, self.research, self.discovery, self.draft,
                            content_format=content_format)

    def intake(self):
        return prepare_brief(self.research, self.draft, self.ready,
                             discovery_pool=self.pool, discovery_receipt=self.discovery)

    def test_authors_replayable_script_storyboard_with_existing_voices(self):
        proof = self.author()
        draft = json.loads(self.draft.read_text())
        self.assertEqual(proof, draft['original_authoring'])
        self.assertEqual(proof['algorithm'], ALGORITHM)
        self.assertEqual(proof['speaker_sequence'], ['narrator', 'dave', 'points_monk', 'narrator'])
        self.assertEqual([scene['speaker'] for scene in draft['scenes']], proof['speaker_sequence'])
        self.assertEqual(draft['layout'], 'landscape')
        monk = draft['scenes'][2]
        self.assertEqual(monk['visual_spec']['gesture'], 'point_right')
        self.assertEqual(monk['visual_spec']['reveal_on_phrase'],
                         json.loads(self.research.read_text())['sources'][1]['claim'])
        self.assertEqual(draft['research_sha256'], hashlib.sha256(self.research.read_bytes()).hexdigest())
        self.assertTrue(all(proof[key] is False for key in FALSE_FLAGS))
        self.assertIs(proof['authorship_verified'], False)
        self.assertIs(proof['originality_review_complete'], False)

        receipt = self.intake()
        brief = json.loads((self.ready / 'brief.json').read_text())
        verified = verify_intake(self.research, self.draft, self.ready,
                                 discovery_pool=self.pool, discovery_receipt=self.discovery)
        editorial = compile_editorial(brief, validate_visual_shapes=True)
        self.assertEqual(receipt['original_authoring'], proof)
        self.assertEqual(verified['original_authoring'], proof)
        self.assertEqual(editorial['original_authoring'], proof)
        self.assertEqual(editorial['scenes'][2]['visual_spec']['reveal_on_phrase'],
                         monk['visual_spec']['reveal_on_phrase'])
        self.assertEqual(editorial['scenes'][2]['visual_spec']['gesture'], 'point_right')
        self.assertIn('authorship and originality review remain unverified', editorial['script_scope'])
        self.assertEqual(brief['topic_discovery'], verified['topic_discovery'])

        request = {'operation': 'produce-content-cycle', 'brief': brief,
                   'brief_sha256': brief_digest(brief), 'timeout_seconds': 300,
                   'publication_enabled': False, 'paid_generation_enabled': False,
                   'intake_input': {
                       'research_json': self.research.read_text(),
                       'draft_json': self.draft.read_text(),
                       'receipt_json': (self.ready / 'intake.json').read_text(),
                       'discovery_pool_json': self.pool.read_text(),
                       'discovery_receipt_json': self.discovery.read_text(),
                   }}
        encoded, lineage, files, queued = production_handoff(request)
        self.assertEqual(json.loads(encoded), brief)
        self.assertIsNone(lineage)
        self.assertEqual(queued['original_authoring'], proof)
        self.assertEqual(set(files), {'research.json', 'draft.json', 'intake.json',
                                      'discovery-pool.json', 'discovery.json'})

        direct = {key: value for key, value in request.items() if key != 'intake_input'}
        with self.assertRaisesRegex(ValueError, 'exact verified intake replay'):
            production_handoff(direct)
        forged_output = self.root / 'forged-direct-cycle'
        with self.assertRaisesRegex(ValueError, 'matching exact verified intake'):
            run_cycle(self.ready / 'brief.json', forged_output,
                      voice_python='/unused', voice_root='/unused')
        self.assertFalse(forged_output.exists())

        changed = copy.deepcopy(brief)
        changed['original_authoring']['research_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'identities differ from verified topic discovery'):
            compile_editorial(changed)

    def test_rejects_edited_draft_and_missing_or_changed_discovery(self):
        self.author()
        changed = json.loads(self.draft.read_text())
        changed['scenes'][1]['narration'] = 'A substituted script line.'
        self.draft.write_text(json.dumps(changed, indent=2, sort_keys=True) + '\n')
        with self.assertRaisesRegex(ValueError, 'does not match the verified research'):
            self.intake()
        self.assertFalse(self.ready.exists())

        self.draft.unlink()
        self.author()
        with self.assertRaisesRegex(ValueError, 'requires exact replayable discovery'):
            prepare_brief(self.research, self.draft, self.ready)
        self.assertFalse(self.ready.exists())
        self.discovery.write_bytes(self.discovery.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            self.intake()
        self.assertFalse(self.ready.exists())

    def test_authors_replayable_long_form_handoff_without_acceptance_claims(self):
        proof = self.author(LONG_FORM_FORMAT)
        draft = json.loads(self.draft.read_text())
        self.assertEqual(proof['schema_version'], 2)
        self.assertEqual(proof['algorithm'], LONG_FORM_ALGORITHM)
        self.assertEqual(proof['content_format'], LONG_FORM_FORMAT)
        self.assertGreaterEqual(proof['planned_duration_seconds'], LONG_FORM_MIN_SECONDS)
        self.assertFalse(proof['long_form_production_verified'])
        self.assertGreaterEqual(len(draft['scenes']), 8)
        self.assertEqual(proof['speaker_sequence'],
                         [scene['speaker'] for scene in draft['scenes']])
        self.assertEqual(proof['speaker_sequence'][0], 'narrator')
        self.assertEqual(proof['speaker_sequence'][-1], 'narrator')
        self.assertTrue({'narrator', 'dave', 'points_monk'} <= set(proof['speaker_sequence']))
        self.assertTrue(all(proof[key] is False for key in FALSE_FLAGS))

        receipt = self.intake()
        brief = json.loads((self.ready / 'brief.json').read_text())
        verified = verify_intake(self.research, self.draft, self.ready,
                                 discovery_pool=self.pool, discovery_receipt=self.discovery)
        editorial = compile_editorial(brief, validate_visual_shapes=True)
        self.assertEqual(receipt['original_authoring'], proof)
        self.assertEqual(verified['original_authoring'], proof)
        self.assertEqual(editorial['original_authoring'], proof)
        self.assertEqual(editorial['planned_duration_seconds'],
                         proof['planned_duration_seconds'])
        self.assertGreater(editorial['planned_duration_seconds'], 60)

        request = {'operation': 'produce-content-cycle', 'brief': brief,
                   'brief_sha256': brief_digest(brief), 'timeout_seconds': 300,
                   'publication_enabled': False, 'paid_generation_enabled': False,
                   'intake_input': {
                       'research_json': self.research.read_text(),
                       'draft_json': self.draft.read_text(),
                       'receipt_json': (self.ready / 'intake.json').read_text(),
                       'discovery_pool_json': self.pool.read_text(),
                       'discovery_receipt_json': self.discovery.read_text(),
                   }}
        _, _, files, queued = production_handoff(request)
        self.assertEqual(queued['original_authoring'], proof)
        self.assertEqual(set(files), {'research.json', 'draft.json', 'intake.json',
                                      'discovery-pool.json', 'discovery.json'})

    def test_long_form_replay_rejects_format_duration_and_voice_forgery(self):
        self.author(LONG_FORM_FORMAT)
        original = self.draft.read_bytes()
        mutations = (
            lambda value: value['original_authoring'].__setitem__(
                'planned_duration_seconds', value['original_authoring']['planned_duration_seconds'] + 1),
            lambda value: value['original_authoring'].__setitem__('content_format', 'standard'),
            lambda value: value['original_authoring']['speaker_sequence'].__setitem__(1, 'narrator'),
            lambda value: value['original_authoring'].__setitem__(
                'long_form_production_verified', True),
        )
        for index, mutate in enumerate(mutations):
            value = json.loads(original)
            mutate(value)
            self.draft.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.intake()
            self.assertFalse(self.ready.exists())
        self.draft.write_bytes(original)

    def test_authoring_fails_closed_on_environment_and_substituted_research(self):
        old = self.research.read_bytes()
        research = json.loads(old)
        research['sources'][0]['claim'] = 'Substituted claim.'
        self.research.write_text(json.dumps(research, indent=2, sort_keys=True) + '\n')
        with self.assertRaisesRegex(ValueError, 'Selected research does not match'):
            self.author()
        self.assertFalse(self.draft.exists())

        self.research.write_bytes(old)
        import os
        previous = os.environ.get('PUBLICATION_ENABLED')
        os.environ['PUBLICATION_ENABLED'] = 'true'
        try:
            with self.assertRaisesRegex(ValueError, 'must remain disabled'):
                self.author()
        finally:
            if previous is None:
                os.environ.pop('PUBLICATION_ENABLED', None)
            else:
                os.environ['PUBLICATION_ENABLED'] = previous
        self.assertFalse(self.draft.exists())


if __name__ == '__main__':
    unittest.main()
