"""Exercise offline review transport and its identity checks."""

import base64
import hashlib
from pathlib import Path
import re
import tempfile
import unittest

from integrations.content_control.offline_review_player import build_player


class OfflineReviewPlayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.video = root / 'candidate.mp4'
        self.captions = root / 'captions.vtt'
        self.output = root / 'offline.html'
        self.video.write_bytes(b'MP4 placeholder bytes for transport tests')
        self.captions.write_bytes(b'WEBVTT\n\n00:00.000 --> 00:02.000\n</script>\n')
        self.pins = dict(video_sha256=hashlib.sha256(self.video.read_bytes()).hexdigest(),
                         caption_sha256=hashlib.sha256(self.captions.read_bytes()).hexdigest())

    def build(self):
        return build_player(self.video, self.captions, self.output, **self.pins)

    def test_original_bytes_are_embedded_and_notes_cannot_approve(self):
        receipt = self.build()
        page = self.output.read_text()
        for label, path in (('picture', self.video), ('sidecar', self.captions)):
            encoded = re.search(fr'<script id="{label}" type="application/octet-stream">([^<]+)</script>', page)
            self.assertEqual(base64.b64decode(encoded.group(1), validate=True), path.read_bytes())
        self.assertEqual(receipt['player_sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertIn("media-src blob:", page)
        self.assertIn("independent_verification: false, full_av_review: false", page)
        self.assertNotIn('src="video.mp4"', page)
        self.assertNotIn('src="captions.vtt"', page)
        with self.assertRaises(FileExistsError):
            self.build()

    def test_changed_input_cannot_write_a_player(self):
        self.captions.write_text('WEBVTT\n\nDifferent captions\n')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_pinned_plain_text_is_not_a_caption_track(self):
        self.captions.write_bytes(b'\n')
        self.pins['caption_sha256'] = hashlib.sha256(self.captions.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'WebVTT captions required'):
            self.build()
        self.assertFalse(self.output.exists())
