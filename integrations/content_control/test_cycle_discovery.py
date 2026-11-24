"""Offline discovery provenance, freshness and downstream replay fixtures."""
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_discovery import (
    DOMAIN_NORMALIZATION, FRESHNESS_POLICY, _json_bytes, _select, select_topic, verify_selection,
)
from integrations.content_control.complete_cycle import run_cycle
from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.cycle_intake import prepare_brief, verify_intake
from integrations.content_control.cycle_job import (
    brief_digest, production_handoff, validate, verify_attempt_intake,
)
from integrations.local_agent_queue import validate as validate_queue


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def source(identifier, domain, retrieved):
    return {'id': identifier, 'url': f'https://{domain}/facts/{identifier}',
            'retrieved_at': iso(retrieved), 'claim': f'Claim {identifier}',
            'excerpt': f'Exact excerpt for {identifier}.'}


def reference(observed, domain='reference.example'):
    return {'url': f'https://{domain}/video', 'observed_at': iso(observed),
            'observation_type': 'metadata', 'patterns': ['A supplied metadata observation.']}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pool = self.root / 'pool.json'
        self.output = self.root / 'selected'
        self.created = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        evidence = self.created - timedelta(days=1)
        self.data = {'schema_version': 1, 'created_at': iso(self.created), 'candidates': [
            {'id': 'fees', 'topic': 'How card fees change reward value',
             'sources': [source('a', 'one.example', evidence), source('b', 'two.example', evidence)],
             'reference_observations': [reference(evidence, 'reference.example')]},
            {'id': 'minimums', 'topic': 'What a minimum payment does',
             'sources': [source('c', 'one.example', evidence), source('d', 'two.example', evidence),
                         source('e', 'three.example', evidence)],
             'reference_observations': [reference(evidence, 'other-reference.example')]},
        ]}

    def write(self):
        self.pool.write_text(json.dumps(self.data))

    def draft(self, research_path):
        draft = self.root / 'draft.json'
        draft.write_text(json.dumps({
            'schema_version': 1,
            'research_sha256': hashlib.sha256(research_path.read_bytes()).hexdigest(),
            'title': 'Minimum payment, maximum confusion',
            'scenes': [{'id': 's1', 'narration': 'A minimum payment is not the full balance.',
                        'visual': 'Dave compares two statement amounts.', 'source_ids': ['c'],
                        'factual': True, 'speaker': 'dave', 'duration_seconds': 5}],
        }))
        return draft

    def discovered_intake(self):
        self.write()
        select_topic(self.pool, self.output)
        research = self.output / 'research.json'
        draft = self.draft(research)
        ready = self.root / 'ready'
        prepare_brief(research, draft, ready, discovery_pool=self.pool,
                      discovery_receipt=self.output / 'discovery.json')
        return research, draft, ready

    def discovered_revision_request(self):
        from integrations.content_control.cycle_lineage import SCOPE
        from integrations.content_control.test_cycle_lineage import handoff

        research, _, ready = self.discovered_intake()
        revised = json.loads((ready / 'brief.json').read_text())
        revised['scenes'][0]['narration'] = 'A minimum payment leaves part of the balance unpaid.'
        raw = json.dumps(revised, indent=2) + '\n'
        lineage = handoff(hashlib.sha256(raw.encode()).hexdigest())
        lineage['schema_version'] = 2
        lineage['topic_discovery_sha256'] = hashlib.sha256(json.dumps(
            revised['topic_discovery'], sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode()).hexdigest()
        revision_receipt = json.dumps(lineage, indent=2) + '\n'
        request = {
            'operation': 'produce-content-cycle', 'brief': revised,
            'brief_sha256': brief_digest(revised), 'timeout_seconds': 300,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'revision_input': {
                'brief_json': raw,
                'revision_lineage': {
                    'schema_version': 1, 'revision_json': revision_receipt,
                    'revision_sha256': hashlib.sha256(revision_receipt.encode()).hexdigest(),
                    'parent_evidence_independently_verified': False,
                    'feedback_resolution_verified': False, 'scope': SCOPE,
                },
                'discovery_pool_json': self.pool.read_text(),
                'discovery_research_json': research.read_text(),
                'discovery_receipt_json': (self.output / 'discovery.json').read_text(),
            },
        }
        return request

    def test_selects_transparently_and_replays_exact_bytes(self):
        self.write()
        receipt = select_topic(self.pool, self.output)
        research = json.loads((self.output / 'research.json').read_text())
        self.assertEqual(receipt['selected_candidate_id'], 'minimums')
        self.assertEqual(receipt['candidate_order'], ['minimums', 'fees'])
        self.assertEqual(receipt['selection_basis']['distinct_source_registrable_domains'], 3)
        self.assertEqual(receipt['domain_normalization'], DOMAIN_NORMALIZATION)
        self.assertEqual(receipt['freshness_policy'], FRESHNESS_POLICY)
        self.assertEqual(receipt['selection_basis']['evidence_timestamp_count'], 4)
        self.assertEqual(research['topic'], 'What a minimum payment does')
        self.assertEqual(receipt['research_sha256'],
                         hashlib.sha256((self.output / 'research.json').read_bytes()).hexdigest())
        self.assertFalse(receipt['competitor_comparison'])
        self.assertFalse(receipt['production_approved'])
        self.assertIn('No trend, popularity', receipt['scope'])
        paths = (self.pool, self.output / 'research.json', self.output / 'discovery.json')
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        proof = verify_selection(self.pool, self.output)
        self.assertEqual(proof['status'], 'DISCOVERY_VERIFIED')
        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in paths], before)

    def test_discovery_proof_survives_intake_queue_and_guardian_replay(self):
        research, draft, ready = self.discovered_intake()
        paths = {'discovery_pool': self.pool, 'discovery_receipt': self.output / 'discovery.json'}
        proof = verify_intake(research, draft, ready, **paths)
        brief = json.loads((ready / 'brief.json').read_text())
        discovery = proof['topic_discovery']
        self.assertEqual(brief['topic_discovery'], discovery)
        self.assertEqual(json.loads((ready / 'intake.json').read_text())['topic_discovery'], discovery)
        self.assertEqual(discovery['research_sha256'], hashlib.sha256(research.read_bytes()).hexdigest())
        self.assertEqual(brief['scenes'][0]['speaker'], 'dave')
        request = {'operation': 'produce-content-cycle', 'brief': brief,
                   'brief_sha256': brief_digest(brief), 'timeout_seconds': 300,
                   'publication_enabled': False, 'paid_generation_enabled': False,
                   'intake_input': {'research_json': research.read_text(), 'draft_json': draft.read_text(),
                                    'receipt_json': (ready / 'intake.json').read_text(),
                                    'discovery_pool_json': self.pool.read_text(),
                                    'discovery_receipt_json': (self.output / 'discovery.json').read_text()}}
        queued = {'id': 'discovery-replay', 'adapter': 'content-control-cycle', 'request': request,
                  'max_attempts': 1, 'publication_enabled': False, 'paid_generation_enabled': False}
        self.assertEqual(validate_queue(queued)['request'], request)
        raw, lineage, files, queued_proof = production_handoff(request)
        self.assertEqual(raw, (ready / 'brief.json').read_bytes())
        self.assertIsNone(lineage)
        self.assertEqual(queued_proof, proof)
        self.assertEqual(files['discovery-pool.json'], self.pool.read_bytes())
        self.assertEqual(files['discovery.json'], (self.output / 'discovery.json').read_bytes())
        attempt = self.root / 'attempt'
        attempt.mkdir()
        (attempt / 'brief.json').write_bytes(raw)
        for name, data in files.items():
            (attempt / name).write_bytes(data)
        verify_attempt_intake(attempt, queued_proof, {'verified_intake': queued_proof})

    def test_exact_research_and_discovery_bytes_are_required_downstream(self):
        research, draft, ready = self.discovered_intake()
        paths = {'discovery_pool': self.pool, 'discovery_receipt': self.output / 'discovery.json'}
        baseline = verify_intake(research, draft, ready, **paths)
        for target in (research, self.pool, self.output / 'discovery.json'):
            with self.subTest(target=target.name):
                original = target.read_bytes()
                target.write_bytes(original + b' ')
                with self.assertRaises(ValueError):
                    verify_intake(research, draft, ready, **paths)
                target.write_bytes(original)
        self.assertEqual(verify_intake(research, draft, ready, **paths), baseline)

    def test_discovery_claim_without_replayable_intake_is_rejected(self):
        _, _, ready = self.discovered_intake()
        brief = json.loads((ready / 'brief.json').read_text())
        request = {'operation': 'produce-content-cycle', 'brief': brief,
                   'brief_sha256': brief_digest(brief), 'timeout_seconds': 300,
                   'publication_enabled': False, 'paid_generation_enabled': False}
        with self.assertRaisesRegex(ValueError, 'replayable verified discovery (?:intake|evidence)'):
            production_handoff(request)
        with self.assertRaisesRegex(ValueError, 'replayable verified discovery (?:intake|evidence)'):
            validate(request)
        output = self.root / 'forged-cycle'
        with self.assertRaisesRegex(ValueError, 'replayable verified discovery (?:intake|evidence)'):
            run_cycle(ready / 'brief.json', output, voice_python='unused', voice_root='unused')
        self.assertFalse(output.exists())

    def test_discovered_revision_replays_and_retains_exact_evidence(self):
        request = self.discovered_revision_request()
        validate(request)
        raw, lineage, files, proof = production_handoff(request)
        self.assertEqual(raw, request['revision_input']['brief_json'].encode())
        self.assertIsNotNone(lineage)
        self.assertEqual(proof, request['brief']['topic_discovery'])
        self.assertEqual(set(files), {
            'discovery-pool.json', 'discovery-research.json', 'discovery.json'})
        attempt = self.root / 'revision-attempt'
        attempt.mkdir()
        (attempt / 'brief.json').write_bytes(raw)
        for name, value in files.items():
            (attempt / name).write_bytes(value)
        verify_attempt_intake(attempt, proof, {'verified_revision_discovery': proof})

    def test_discovered_revision_guardian_passes_evidence_to_cycle(self):
        import sys
        from integrations.content_control.cycle_job import run_job
        from integrations.content_control.test_cycle_job import packet, write

        request = self.discovered_revision_request()
        raw, lineage, _, proof = production_handoff(request)
        source = self.root / 'voice-source'
        (source / 'scripts').mkdir(parents=True)
        (source / 'scripts/v2_free_voice.py').write_text('')
        attempt = self.root / 'guarded-revision'
        attempt.mkdir()

        def runner(command, **kwargs):
            self.assertIn('revision_discovery_inputs=dict(', command[2])
            self.assertNotIn('intake_inputs=dict(', command[2])
            self.assertEqual(command[-3:], [
                str(attempt / 'discovery-pool.json'),
                str(attempt / 'discovery-research.json'),
                str(attempt / 'discovery.json'),
            ])
            receipt = packet(attempt / 'cycle', hashlib.sha256(raw).hexdigest(),
                             source_brief=request['brief'])
            (attempt / 'cycle/brief.json').write_bytes(raw)
            receipt['revision_lineage'] = copy.deepcopy(lineage)
            receipt['verified_revision_discovery'] = copy.deepcopy(proof)
            write(attempt / 'cycle/cycle.json', receipt)

        with patch('integrations.content_control.cycle_job.collect_snapshot', return_value={}), \
             patch('integrations.content_control.cycle_job.recommend_capacity',
                   return_value={'admitted_workers': 1}), \
             patch('integrations.content_control.cycle_job.guarded_runner',
                   return_value=runner):
            result = run_job(request, attempt, voice_python=sys.executable,
                             voice_root=source)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['verified_revision_discovery'], proof)
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['paid_generation_enabled'])

    def test_discovered_revision_rejects_missing_tampered_or_substituted_evidence(self):
        request = self.discovered_revision_request()
        cases = []
        missing = copy.deepcopy(request)
        del missing['revision_input']['discovery_receipt_json']
        cases.append(missing)
        for field in ('discovery_pool_json', 'discovery_research_json',
                      'discovery_receipt_json'):
            changed = copy.deepcopy(request)
            changed['revision_input'][field] += ' '
            cases.append(changed)
        changed = copy.deepcopy(request)
        changed['brief']['topic'] = 'A substituted topic'
        changed['brief_sha256'] = brief_digest(changed['brief'])
        changed['revision_input']['brief_json'] = json.dumps(changed['brief'], indent=2) + '\n'
        from integrations.content_control.test_cycle_lineage import handoff
        from integrations.content_control.cycle_lineage import SCOPE
        lineage = handoff(hashlib.sha256(
            changed['revision_input']['brief_json'].encode()).hexdigest())
        lineage['schema_version'] = 2
        lineage['topic_discovery_sha256'] = hashlib.sha256(json.dumps(
            changed['brief']['topic_discovery'], sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode()).hexdigest()
        receipt = json.dumps(lineage, indent=2) + '\n'
        changed['revision_input']['revision_lineage'] = {
            'schema_version': 1, 'revision_json': receipt,
            'revision_sha256': hashlib.sha256(receipt.encode()).hexdigest(),
            'parent_evidence_independently_verified': False,
            'feedback_resolution_verified': False, 'scope': SCOPE,
        }
        cases.append(changed)
        for item in cases:
            with self.subTest(fields=set(item['revision_input'])), self.assertRaises(ValueError):
                validate(item)

    def test_discovery_schema_version_rejects_boolean(self):
        _, _, ready = self.discovered_intake()
        brief = json.loads((ready / 'brief.json').read_text())
        brief['topic_discovery']['schema_version'] = True
        with self.assertRaisesRegex(ValueError, 'exact unapproved evidence handoff'):
            compile_editorial(brief)

    def test_subdomain_padding_does_not_overstate_independence(self):
        evidence = self.created - timedelta(days=1)
        for domains in (('a.news.example', 'b.news.example'),
                        ('a.publisher.co.uk', 'b.publisher.co.uk')):
            with self.subTest(domains=domains):
                changed = copy.deepcopy(self.data)
                changed['candidates'][1]['sources'] = [source('x', domains[0], evidence),
                                                       source('y', domains[1], evidence)]
                with self.assertRaisesRegex(ValueError, 'registrable source domains'):
                    _select(_json_bytes(changed), iso(self.created + timedelta(hours=1)))

    def test_ip_addresses_cannot_establish_source_independence(self):
        evidence = self.created - timedelta(days=1)
        changed = copy.deepcopy(self.data)
        changed['candidates'][1]['sources'] = [source('x', '192.0.2.1', evidence),
                                               source('y', '198.51.100.2', evidence)]
        with self.assertRaisesRegex(ValueError, 'IP addresses cannot establish'):
            _select(_json_bytes(changed), iso(self.created + timedelta(hours=1)))

    def test_all_evidence_recency_includes_reference_timestamps(self):
        evidence = self.created - timedelta(days=2)
        for candidate in self.data['candidates']:
            candidate['sources'] = candidate['sources'][:2]
            for item in candidate['sources']:
                item['retrieved_at'] = iso(evidence)
        self.data['candidates'][0]['reference_observations'][0]['observed_at'] = iso(self.created - timedelta(minutes=1))
        self.data['candidates'][1]['reference_observations'][0]['observed_at'] = iso(self.created - timedelta(hours=1))
        _, _, receipt = _select(_json_bytes(self.data), iso(self.created + timedelta(hours=1)))
        self.assertEqual(receipt['selected_candidate_id'], 'fees')
        self.assertEqual(receipt['selection_basis']['newest_evidence_at'],
                         iso(self.created - timedelta(minutes=1)))

    def test_all_declared_timestamps_affect_the_recency_score(self):
        old = self.created - timedelta(days=10)
        recent = self.created - timedelta(days=1)
        for candidate in self.data['candidates']:
            candidate['sources'] = candidate['sources'][:2]
            for item in candidate['sources']:
                item['retrieved_at'] = iso(recent)
            candidate['reference_observations'][0]['observed_at'] = iso(recent)
        self.data['candidates'][0]['sources'][0]['retrieved_at'] = iso(old)
        _, _, receipt = _select(_json_bytes(self.data), iso(self.created + timedelta(hours=1)))
        self.assertEqual(receipt['selected_candidate_id'], 'minimums')
        basis = receipt['selection_basis']
        self.assertEqual(basis['oldest_evidence_at'], iso(recent))
        self.assertEqual(basis['mean_evidence_at'], iso(recent))

    def test_freshness_boundaries_are_closed_and_replayable(self):
        boundary = copy.deepcopy(self.data)
        created = self.created - timedelta(days=1)
        boundary['created_at'] = iso(created)
        oldest = created - timedelta(days=30)
        for candidate in boundary['candidates']:
            for item in candidate['sources']:
                item['retrieved_at'] = iso(created - timedelta(days=1))
            for item in candidate['reference_observations']:
                item['observed_at'] = iso(created - timedelta(days=1))
        boundary['candidates'][0]['sources'][0]['retrieved_at'] = iso(oldest)
        raw = _json_bytes(boundary)
        _select(raw, iso(created + timedelta(hours=24)))
        with self.assertRaisesRegex(ValueError, 'selected within'):
            _select(raw, iso(created + timedelta(hours=24, seconds=1)))
        boundary['candidates'][0]['sources'][0]['retrieved_at'] = iso(oldest - timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, 'freshness window'):
            _select(_json_bytes(boundary), iso(created + timedelta(hours=1)))

    def test_rejects_duplicates_future_evidence_and_single_domain(self):
        evidence = self.created - timedelta(days=1)
        cases = (
            (lambda value: value['candidates'].__setitem__(1, dict(value['candidates'][1], id='fees')),
             'IDs must be unique'),
            (lambda value: value['candidates'][1].update(topic=value['candidates'][0]['topic']),
             'topics must be unique'),
            (lambda value: value['candidates'][1].update(sources=[
                source('x', 'one.example', evidence), source('y', 'one.example', evidence)]),
             'registrable source domains'),
            (lambda value: value['candidates'][1]['sources'][0].update(
                retrieved_at=iso(self.created + timedelta(seconds=1))), 'newer than the candidate pool'),
            (lambda value: value['candidates'][1]['reference_observations'][0].update(
                observed_at=iso(self.created + timedelta(seconds=1))), 'newer than the candidate pool'),
        )
        for change, error in cases:
            with self.subTest(error=error):
                changed = copy.deepcopy(self.data)
                change(changed)
                with self.assertRaisesRegex(ValueError, error):
                    _select(_json_bytes(changed), iso(self.created + timedelta(hours=1)))

    def test_publication_or_paid_generation_blocks_before_output(self):
        self.write()
        for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED'):
            with patch.dict(os.environ, {key: 'true'}), self.assertRaisesRegex(
                    ValueError, 'must remain disabled'):
                select_topic(self.pool, self.output)
            self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
