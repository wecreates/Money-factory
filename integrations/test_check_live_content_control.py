import unittest
from unittest.mock import patch
from check_live_content_control import build_report, social_summary, observe


def response(body, status=200):
    return {'http_status': status, 'body': body}


class SocialMonitorTest(unittest.TestCase):
    def setUp(self):
        self.runtime = response({'status': 'NOT_ACTIVATED', 'publication_enabled': False,
            'external_writes_enabled': False, 'missing_configuration': [],
            'authorization_configuration': {'owner': {'missing_configuration': ['OWNER_GITHUB_CLIENT_ID']}},
            'storage_bootstrap': {'read_verified': True, 'checked_at': '2026-10-13T00:00:00Z'},
            'storage_health': {'status': 'STARTUP_OBSERVATION_ONLY', 'live_database_checked': False, 'availability_verified': False}})
        self.links = response({'publication_enabled': False, 'references': [{'reference_checks': [
            {'status': 'verified_repository_evidence', 'evidence_verified': True}]}]})
        self.status = response({'publication_enabled': False, 'connection_health': [{'platform': 'instagram', 'status': 'UNCONNECTED'}]})

    def summary(self):
        return social_summary(self.runtime, self.links, self.status)

    def test_transport_malformed_json_is_observation_error(self):
        class Response:
            status = 200
            headers = {'Content-Type': 'application/json'}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{not-json'
        with patch('check_live_content_control.urllib.request.urlopen', return_value=Response()):
            result = observe('/api/social/runtime')
        self.assertEqual(result['error'], 'JSONDecodeError')
        self.assertNotIn('body', result)

    def test_historical_read_never_promoted_to_live_or_durable(self):
        summary = self.summary()
        self.assertTrue(summary['storage']['startup_read_verified'])
        self.assertFalse(summary['storage']['live_database_available'])
        self.assertFalse(summary['storage']['durability_verified_by_this_monitor'])
        self.assertFalse(summary['connections_live_verified_by_this_monitor'])

    def test_live_requires_both_explicit_booleans(self):
        health = self.runtime['body']['storage_health']
        for checked, available, expected in [(True, True, True), (True, False, False), ('true', True, False), (True, 1, False)]:
            health.update(live_database_checked=checked, availability_verified=available)
            self.assertIs(self.summary()['storage']['live_database_available'], expected)

    def test_missing_configuration_retained_without_credentials(self):
        self.assertEqual(self.summary()['missing_authorization_configuration']['owner'], ['OWNER_GITHUB_CLIENT_ID'])
        self.assertEqual(self.summary()['missing_storage_configuration'], [])
        self.runtime['body']['missing_configuration'] = 'bad'
        self.assertIsNone(self.summary()['missing_storage_configuration'])

    def test_flags_must_explicitly_be_false_on_all_endpoints(self):
        self.assertEqual(self.summary()['publication_policy'], 'REPORTED_DISABLED')
        for value in [True, None, 0, 'false']:
            self.links['body']['publication_enabled'] = value
            self.assertEqual(self.summary()['publication_policy'], 'UNVERIFIED_OR_UNSAFE')

    def test_malformed_and_failed_responses_are_unknown(self):
        for value in [None, [], 'bad', 42]:
            self.runtime = response(value)
            summary = self.summary()
            self.assertFalse(summary['runtime_response_valid'])
            self.assertEqual(summary['runtime_status'], 'UNKNOWN')
        self.runtime = response({'publication_enabled': False, 'status': 'READY'}, 503)
        self.assertEqual(self.summary()['runtime_status'], 'UNKNOWN')

    def test_nested_malformed_values_do_not_crash(self):
        self.runtime = response({'storage_health': [], 'storage_bootstrap': 'bad', 'authorization_configuration': []})
        self.status = response({'connection_health': [None, 'bad']})
        self.links = response({'references': [{'reference_checks': [None]}]})
        self.assertFalse(self.summary()['evidence_routing']['response_schema_valid'])
        self.assertEqual(self.summary()['connection_observations'], [])

    def test_repository_links_do_not_prove_execution_or_complete_analysis(self):
        routing = self.summary()['evidence_routing']
        self.assertEqual(routing['verified_reference_count'], 1)
        self.assertEqual(routing['status'], 'VERIFIED_REPOSITORY_REFERENCES')
        self.assertFalse(routing['runtime_routing_verified'])
        self.assertFalse(routing['revenue_verified'])
        self.links['body']['references'][0]['reference_checks'][0]['status'] = 'finding_missing'
        self.assertEqual(self.summary()['evidence_routing']['status'], 'INVALID_REFERENCES')

    def test_empty_links_not_vacuously_verified(self):
        self.links['body']['references'] = []
        self.assertEqual(self.summary()['evidence_routing']['status'], 'NO_VERIFIED_REFERENCES')

    def test_overall_readiness_never_promoted_and_media_hash_preserved(self):
        observations = [{'path': '/health', **response({'expectedSha256': 'abc', 'actualSha256': 'abc'})},
                        {'path': '/media', 'http_status': 200, 'sha256': 'abc'},
                        {'path': '/media', 'http_status': 206, 'sha256': 'range'}]
        report = build_report(observations)
        self.assertTrue(report['accepted_media_hash_matches_health'])
        self.assertFalse(report['production_ready'])
        self.assertFalse(build_report([])['accepted_media_hash_matches_health'])


if __name__ == '__main__':
    unittest.main()
