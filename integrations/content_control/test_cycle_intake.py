"""Fixtures exercise the handoff contract; actual sources are checked separately."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.content_control.cycle_intake import prepare_brief
from integrations.content_control.cycle_job import brief_digest
from integrations.content_control.test_cycle_editorial import brief as sample_brief


class IntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.research, self.draft, self.output = (root / name for name in ('research.json', 'draft.json', 'ready'))
        fixture = sample_brief()
        self.research_data = {key: fixture[key] for key in ('schema_version', 'topic', 'sources', 'reference_observations')}
        self.research.write_text(json.dumps(self.research_data))
        self.draft_data = {key: fixture[key] for key in ('schema_version', 'title', 'scenes')}
        self.draft_data['research_sha256'] = hashlib.sha256(self.research.read_bytes()).hexdigest()

    def write_draft(self):
        self.draft.write_text(json.dumps(self.draft_data))

    def test_ready_brief_preserves_sources_and_binds_exact_draft(self):
        self.write_draft()
        receipt = prepare_brief(self.research, self.draft, self.output)
        raw = (self.output / 'brief.json').read_bytes()
        output = json.loads(raw)
        self.assertEqual(output['sources'], self.research_data['sources'])
        self.assertEqual(output['scenes'], self.draft_data['scenes'])
        self.assertEqual(receipt['draft_sha256'], hashlib.sha256(self.draft.read_bytes()).hexdigest())
        self.assertEqual(receipt['brief_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['queue_brief_sha256'], brief_digest(output))
        self.assertEqual(receipt, json.loads((self.output / 'intake.json').read_text()))
        self.assertFalse(receipt['factual_review'])
        self.assertFalse(receipt['production_approved'])
        with self.assertRaisesRegex(ValueError, 'Fresh intake'):
            prepare_brief(self.research, self.draft, self.output)

    def test_draft_cannot_replace_research_or_cite_unknown_records(self):
        self.draft_data['sources'] = []
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'Unexpected intake fields'):
            prepare_brief(self.research, self.draft, self.output)
        del self.draft_data['sources']
        self.draft_data['scenes'][0]['source_ids'] = ['invented']
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'unknown source'):
            prepare_brief(self.research, self.draft, self.output)
        self.assertFalse(self.output.exists())

    def test_draft_rejects_even_whitespace_changes_to_research(self):
        self.write_draft()
        self.research.write_bytes(self.research.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'exact research bytes'):
            prepare_brief(self.research, self.draft, self.output)
        self.assertFalse(self.output.exists())

    def test_formatted_brief_must_fit_renderer_limit(self):
        self.draft_data['scenes'][0]['unused'] = [[0] * 100] * 300
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'Formatted brief exceeds renderer'):
            prepare_brief(self.research, self.draft, self.output)
        self.assertFalse(self.output.exists())
