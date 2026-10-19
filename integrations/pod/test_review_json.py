"""Ambiguous JSON must not become review or recovery evidence."""
import hashlib
import json
import unittest
from unittest.mock import patch

import inspect_review as inspection
import test_production_snapshot as fixture


class ReviewJSONTests(unittest.TestCase):
    def case(self):
        case = fixture.ProductionSnapshotTests(); case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def complete(self, case):
        with patch.object(fixture.agent, 'run_review_child', side_effect=case.finish):
            return case.run_agent()

    def test_duplicate_job_keys_fail_before_generation(self):
        for extra in (b'"publication_enabled":true,"publication_enabled":false',
                      b'"publication_enabled":false',
                      b'"publication_\\u0065nabled":false',
                      b'"metadata":{"x":1,"x":2}'):
            with self.subTest(extra=extra):
                case = self.case(); case.job.write_bytes(case.body.rstrip()[:-1]+b','+extra+b'}')
                with patch.object(fixture.agent, 'run_review_child', side_effect=AssertionError('child reached')):
                    with self.assertRaisesRegex(ValueError, '^REVIEW_JSON_DUPLICATE_KEY$'): case.run_agent()
                self.assertFalse(case.output.exists())

    def test_nonfinite_job_numbers_fail_before_generation(self):
        for token in (b'NaN', b'Infinity', b'-Infinity', b'1e400', b'-1e400'):
            with self.subTest(token=token):
                case = self.case(); case.job.write_bytes(case.body.rstrip()[:-1]+b',"metadata":{"x":'+token+b'}}')
                with patch.object(fixture.agent, 'run_review_child', side_effect=AssertionError('child reached')):
                    with self.assertRaisesRegex(ValueError, '^REVIEW_JSON_NONFINITE$'): case.run_agent()
                self.assertFalse(case.output.exists())

    def test_duplicate_result_and_manifest_never_commit_receipt(self):
        for name in ('result.json', 'package/manifest.json'):
            with self.subTest(name=name):
                case = self.case()
                def child(argv, **kwargs):
                    case.finish(argv, **kwargs); path = case.output/name
                    path.write_bytes(path.read_bytes().replace(b'"publication_enabled": false',
                        b'"publication_enabled": true, "publication_enabled": false'))
                with patch.object(fixture.agent, 'run_review_child', side_effect=child):
                    with self.assertRaisesRegex(ValueError, '^REVIEW_JSON_DUPLICATE_KEY$'): case.run_agent()
                self.assertFalse((case.output/'money-factory-receipt.json').exists())

    def test_nonfinite_outputs_are_rejected_by_the_parser(self):
        for name in ('result.json', 'package/manifest.json'):
            with self.subTest(name=name):
                case = self.case()
                def child(argv, **kwargs):
                    case.finish(argv, **kwargs); path = case.output/name
                    path.write_bytes(path.read_bytes()[:-1]+b',"extra":1e400}')
                with patch.object(fixture.agent, 'run_review_child', side_effect=child):
                    with self.assertRaisesRegex(ValueError, '^REVIEW_JSON_NONFINITE$'): case.run_agent()
                self.assertFalse((case.output/'money-factory-receipt.json').exists())

    def test_recovery_rejects_duplicate_receipt_without_rewriting_it(self):
        case = self.case(); self.complete(case)
        path = case.output/'money-factory-receipt.json'
        body = path.read_bytes().replace(b'"publication_enabled": false',
            b'"publication_enabled": true, "publication_enabled": false')
        path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, '^REVIEW_JSON_DUPLICATE_KEY$'):
            inspection.inspect_review(case.job, case.output)
        self.assertEqual(path.read_bytes(), body)

    def test_recovery_rejects_duplicate_job_before_reading_outputs(self):
        case = self.case(); self.complete(case)
        body = case.body.rstrip()[:-1]+b',"publication_enabled":false}'
        case.job.write_bytes(body)
        # Bind the exact ambiguous bytes so input-hash mismatch cannot mask the bug.
        path = case.output/'money-factory-receipt.json'; receipt = json.loads(path.read_text())
        receipt['input_sha256'] = hashlib.sha256(body).hexdigest(); path.write_text(json.dumps(receipt))
        with patch.object(inspection, 'validate_review_output', side_effect=AssertionError('output reached')):
            with self.assertRaisesRegex(ValueError, '^REVIEW_JSON_DUPLICATE_KEY$'):
                inspection.inspect_review(case.job, case.output)

    def test_repeated_names_in_distinct_objects_and_finite_unicode_input_survive(self):
        case = self.case()
        body = case.body.rstrip()[:-1]+',"a":{"x":1.25},"b":{"x":1e-3},"note":"Étoile 日本語"}'.encode()
        case.job.write_bytes(body); receipt = self.complete(case)
        self.assertEqual(receipt['input_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(inspection.inspect_review(case.job, case.output)['status'], 'VERIFIED_REVIEW_FILES')


if __name__ == '__main__': unittest.main()
