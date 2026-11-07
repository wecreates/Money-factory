import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openproject.adapter import dispatch, export_work_packages, import_work_packages


def fixture():
    return {'queue_kind': 'content-control', 'queue': {'version': 1, 'queue': [
        {'id': 'content-review', 'title': 'Review content', 'status': 'BLOCKED',
         'instruction': 'Verify the source claims.', 'publication_enabled': False},
        {'id': 'other-task', 'title': 'Keep private', 'status': 'READY', 'secret': 'never-export'}]},
        'selected_ids': ['content-review'], 'project_id': 7, 'type_id': 1}


def imported():
    data = fixture()
    data['mappings'] = [{'queue_id': 'content-review', 'work_package_id': 42}]
    data['collection'] = {'_type': 'Collection', 'total': 100, '_links': {'nextByOffset': {'href': '/api/v3/work_packages?offset=2'}},
        '_embedded': {'elements': [{'_type': 'WorkPackage', 'id': 42, 'lockVersion': 3,
            'subject': 'Review content', '_links': {'self': {'href': '/api/v3/work_packages/42'},
                'status': {'href': '/api/v3/statuses/8', 'title': 'Closed'}}}]}}
    return data


class OpenProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'input.json'
        self.path.write_text(json.dumps(fixture()))
        self.job = {'tool': 'openproject', 'operation': 'export-work-packages',
                    'input': str(self.path), 'publication_enabled': False,
                    'paid_generation_enabled': False}

    def test_existing_content_queue_exports_api_v3_request(self):
        result = dispatch(self.job)
        request = result['requests'][0]
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(request['path'], '/api/v3/projects/7/work_packages?notify=false')
        self.assertEqual(request['body']['_links']['type']['href'], '/api/v3/types/1')
        self.assertEqual(request['validation']['path'], '/api/v3/projects/7/work_packages/form')
        self.assertFalse(result['dispatch_allowed'])
        self.assertFalse(request['sent'])

    def test_money_factory_queue_shape_supported(self):
        data = {'queue_kind': 'money-factory', 'queue': {'schema_version': 1, 'items': [
            {'id': 'tool', 'target': 'Existing task workflow', 'status': 'pending', 'acceptance': 'Verify actual operation'}]},
            'selected_ids': ['tool'], 'project_id': 4, 'type_id': 2}
        result = export_work_packages(data)
        self.assertEqual(result['requests'][0]['client_reference'], 'cyzor:money-factory:tool')

    def test_only_selected_allowlisted_fields_exported(self):
        data = fixture()
        data['queue']['queue'][0]['secret'] = 'also-never-export'
        result = json.dumps(export_work_packages(data))
        self.assertNotIn('never-export', result)
        self.assertNotIn('other-task', result)
        self.assertNotIn('Keep private', result)

    def test_stable_reference_is_not_false_idempotency_claim(self):
        first = export_work_packages(fixture())['requests'][0]
        data = fixture()
        data['queue']['queue'][0]['title'] = 'Edited title'
        second = export_work_packages(data)['requests'][0]
        self.assertEqual(first['client_reference'], second['client_reference'])
        self.assertTrue(first['deduplication_required'])

    def test_update_requires_lock_version_and_never_blindly_overwrites(self):
        data = fixture()
        data['mappings'] = [{'queue_id': 'content-review', 'work_package_id': 42}]
        with self.assertRaises(ValueError):
            export_work_packages(data)
        data['mappings'][0]['lock_version'] = 0
        request = export_work_packages(data)['requests'][0]
        self.assertEqual(request['method'], 'PATCH')
        self.assertEqual(request['body']['lockVersion'], 0)
        self.assertEqual(request['path'], '/api/v3/work_packages/42?notify=false')

    def test_unknown_duplicate_or_unselected_ids_rejected(self):
        for selected in [[], ['absent'], ['content-review', 'content-review'], [True]]:
            data = fixture()
            data['selected_ids'] = selected
            with self.assertRaises(ValueError):
                export_work_packages(data)

    def test_ids_cannot_be_bools_negative_or_route_injections(self):
        for value in [True, 0, -1, '7/../../admin', 2**53]:
            data = fixture()
            data['project_id'] = value
            with self.assertRaises(ValueError):
                export_work_packages(data)

    def test_duplicate_queue_records_and_mapping_rejected(self):
        data = fixture()
        data['queue']['queue'].append(copy.deepcopy(data['queue']['queue'][0]))
        with self.assertRaises(ValueError):
            export_work_packages(data)
        data = imported()
        data['mappings'].append(copy.deepcopy(data['mappings'][0]))
        with self.assertRaises(ValueError):
            import_work_packages(data)

    def test_import_observes_closed_without_advancing_local_status(self):
        data = imported()
        before = copy.deepcopy(data)
        result = import_work_packages(data)
        record = result['queue']['queue'][0]
        self.assertEqual(record['status'], 'BLOCKED')
        self.assertEqual(record['openproject_observation']['status_title'], 'Closed')
        self.assertFalse(record['publication_enabled'])
        self.assertFalse(result['local_statuses_changed'])
        self.assertFalse(result['full_snapshot_verified'])
        self.assertEqual(before, data)

    def test_partial_missing_rows_do_not_delete_or_close_tasks(self):
        data = imported()
        data['collection']['_embedded']['elements'] = []
        result = import_work_packages(data)
        self.assertEqual(result['unresolved_queue_ids'], ['content-review'])
        self.assertEqual(result['queue'], data['queue'])

    def test_no_heuristic_matching_or_unmapped_imports(self):
        data = imported()
        data['mappings'] = []
        with self.assertRaises(ValueError):
            import_work_packages(data)

    def test_external_or_mismatched_self_links_rejected(self):
        for href in ['https://attacker.example/api/v3/work_packages/42', '/api/v3/work_packages/43', '/api/v3/work_packages/42?token=secret']:
            data = imported()
            data['collection']['_embedded']['elements'][0]['_links']['self']['href'] = href
            with self.assertRaises(ValueError):
                import_work_packages(data)

    def test_import_rejects_invalid_lock_status_and_duplicate_rows(self):
        data = imported()
        data['collection']['_embedded']['elements'][0]['lockVersion'] = True
        with self.assertRaises(ValueError):
            import_work_packages(data)
        data = imported()
        data['collection']['_embedded']['elements'][0]['_links']['status']['href'] = 'https://elsewhere.test'
        with self.assertRaises(ValueError):
            import_work_packages(data)
        data = imported()
        data['collection']['_embedded']['elements'] *= 2
        with self.assertRaises(ValueError):
            import_work_packages(data)

    def test_readiness_does_not_claim_live_connection(self):
        result = dispatch({**self.job, 'operation': 'readiness', 'server_ready': True})
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['server_runtime_verified'])

    def test_explicit_flags_and_unknown_operations_fail_closed(self):
        for update in [{'publication_enabled': True}, {'paid_generation_enabled': None}, {'operation': 'send'}]:
            with self.assertRaises(ValueError):
                dispatch({**self.job, **update})

    def test_input_limits_symlinks_and_special_files(self):
        link = self.path.parent / 'link'
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            dispatch({**self.job, 'input': str(link)})
        self.path.write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            dispatch(self.job)
        fifo = self.path.parent / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            dispatch({**self.job, 'input': str(fifo)})

    def test_symlink_parent_and_parent_traversal_rejected(self):
        alias = self.path.parent / 'alias'
        alias.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink ancestors'):
            dispatch({**self.job, 'input': str(alias / self.path.name)})
        child = self.path.parent / 'child'
        child.mkdir()
        with self.assertRaisesRegex(ValueError, 'Parent traversal'):
            dispatch({**self.job, 'input': str(child / '..' / self.path.name)})

    def test_ancestor_swap_after_open_cannot_redirect_read(self):
        trusted = self.path.parent / 'trusted'
        trusted.mkdir()
        (trusted / 'input.json').write_text(json.dumps(fixture()))
        outside = self.path.parent / 'outside'
        outside.mkdir()
        (outside / 'input.json').write_text('{}')
        real_open = os.open
        moved = self.path.parent / 'moved'

        def swapping_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == 'trusted' and kwargs.get('dir_fd') is not None:
                trusted.rename(moved)
                trusted.symlink_to(outside, target_is_directory=True)
            return descriptor

        with patch('os.open', side_effect=swapping_open) as opened:
            with patch('os.supports_dir_fd', {opened}):
                result = dispatch({**self.job, 'input': str(trusted / 'input.json')})
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['requests'][0]['queue_id'], 'content-review')

    def test_import_dispatch_and_no_network_or_subprocess(self):
        self.path.write_text(json.dumps(imported()))
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), patch('subprocess.run', side_effect=AssertionError('execution forbidden')):
            result = dispatch({**self.job, 'operation': 'import-work-packages'}, '/untrusted/source')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['network_requests'], 0)
        self.assertFalse(result['upstream_executed'])


if __name__ == '__main__':
    unittest.main()
