"""Synthetic revision receipts test identity retention, never creative review."""
import json
from pathlib import Path
import tempfile
import unittest

from integrations.content_control import cycle_lineage as m


def handoff(brief_sha256):
    return {'schema_version': 1, 'status': 'REVISION_BRIEF_READY',
            'supersedes_candidate_sha256': '1' * 64, 'recorded_review_sha256': '2' * 64,
            'prior_cycle_sha256': '3' * 64, 'brief_sha256': brief_sha256,
            'feedback': [{'check': 'visual_readability', 'action': 'Synthetic feedback: enlarge the diagram labels.'}],
            **{flag: False for flag in m.FLAGS},
            'scope': 'Revised supplied brief; previous approval statements cannot certify a new render.'}


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'revision.json'
        self.brief_sha = '4' * 64
        self.receipt = handoff(self.brief_sha)

    def load(self, receipt=None):
        self.path.write_text(json.dumps(receipt or self.receipt, indent=3) + '\n', encoding='utf-8')
        return m.read_revision(self.path, self.brief_sha)

    def test_exact_bytes_and_scope_retained(self):
        value = self.load()
        self.assertEqual(value['revision_json'].encode('utf-8'), self.path.read_bytes())
        self.assertEqual(m.validate_lineage(value, self.brief_sha), self.receipt)
        self.assertFalse(value['parent_evidence_independently_verified'])
        self.assertFalse(value['feedback_resolution_verified'])

    def test_strict_comparison_routing_handoff_is_distinct_and_replayable(self):
        receipt = dict(self.receipt,
                       schema_version=3,
                       recorded_review_schema_version=2,
                       comparison_findings_routing_verified=True,
                       live_comparison_receipt_sha256='5' * 64,
                       live_comparison_observations_sha256='6' * 64,
                       live_comparison_receipt_file_sha256='7' * 64)
        receipt['feedback'] = [{
            'check': 'reference_comparison',
            'action': 'Synthetic comparator repair retained for lineage validation.',
        }]
        value = self.load(receipt)
        self.assertEqual(m.validate_lineage(value, self.brief_sha), receipt)
        for patch in (
                {'recorded_review_schema_version': 1},
                {'comparison_findings_routing_verified': False},
                {'live_comparison_receipt_sha256': 'broken'},
                {'feedback': [dict(item) for item in self.receipt['feedback']]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.load(dict(receipt, **patch))

    def test_wrong_brief_and_invalid_receipt_rejected(self):
        for key, invalid in [('brief_sha256', '9' * 64), ('prior_cycle_sha256', 'broken'),
                             ('publication_enabled', True), ('feedback_resolution_verified', True),
                             ('schema_version', True), ('status', 'APPROVED'), ('scope', 'approved'),
                             ('feedback', [{'check': 'x', 'action': 1}])]:
            with self.subTest(key=key):
                value = dict(self.receipt, **{key: invalid})
                with self.assertRaises(ValueError): self.load(value)

    def test_embedded_tampering_and_promotion_rejected(self):
        original = self.load()
        for key, invalid in [('revision_json', original['revision_json'] + ' '),
                             ('revision_sha256', '0' * 64), ('schema_version', True),
                             ('parent_evidence_independently_verified', True),
                             ('feedback_resolution_verified', True)]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    m.validate_lineage(dict(original, **{key: invalid}), self.brief_sha)

    def test_duplicate_keys_nonfinite_and_unknown_fields_rejected(self):
        good = json.dumps(self.receipt)
        for raw in ['{"schema_version":1,' + good[1:], good.replace('false', 'NaN', 1),
                    good[:-1] + ',"production_ready_override":true}']:
            self.path.write_text(raw)
            with self.assertRaises(ValueError): m.read_revision(self.path, self.brief_sha)

    def test_oversized_invalid_utf8_and_symlink_rejected(self):
        for raw in [b' ' * (m.LIMIT + 1), b'\xff']:
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError): m.read_revision(self.path, self.brief_sha)
        self.load()
        link = self.path.with_name('linked.json'); link.symlink_to(self.path)
        with self.assertRaises(ValueError): m.read_revision(link, self.brief_sha)


if __name__ == '__main__': unittest.main()
