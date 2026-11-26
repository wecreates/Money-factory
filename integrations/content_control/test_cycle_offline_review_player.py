"""Exercise offline review transport and its identity checks."""

import base64
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
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
        self.assertIn("independent_acceptance: false, full_av_acceptance: false", page)
        self.assertIn("crypto.subtle.digest('SHA-256'", page)
        self.assertIn("natural_pass_complete", page)
        self.assertRegex(page, r"state\.invalidations = \[\];\s+state\.events = \[\];\s+logEvent\('natural_pass_reset'\)")
        self.assertIn("record_sha256", page)
        self.assertIn("competitor_comparison_included: false", page)
        self.assertIn("physical_phone_verified: false", page)
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

    @unittest.skipUnless(shutil.which('node'), 'Node needed to execute the player script')
    def test_sidecar_pass_requires_loaded_visible_cues_throughout_playback(self):
        self.build()
        subprocess.run(
            ['node', '-e', r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(process.argv[1], 'utf8').match(/<script>([\s\S]+)<\/script>/)[1];
function setup() {
  const fields = new Map();
  class Element extends EventTarget {
    textContent = 'AA==';
    setAttribute() {}
  }
  const track = Object.assign(new Element(), {
    readyState: 2, track: {mode: 'hidden', cues: [{}]},
  });
  const player = Object.assign(new Element(), {
    currentTime: 0, duration: 10, volume: 1, playbackRate: 1, muted: false,
    textTracks: new EventTarget(), append() {},
  });
  const document = Object.assign(new EventTarget(), {
    hidden: false,
    createElement: () => track,
    getElementById(id) {
      if (id === 'player') return player;
      if (!fields.has(id)) fields.set(id, new Element());
      return fields.get(id);
    },
  });
  const context = vm.createContext({
    document, atob, HTMLTrackElement: {LOADED: 2},
    crypto: {subtle: {digest: () => new Promise(() => {})}},
  });
  vm.runInContext(script, context);
  track.track.mode = 'showing';
  return {document, player, track, state: vm.runInContext('state', context)};
}
function run(before, during, expected) {
  const review = setup();
  before(review);
  review.player.dispatchEvent(new Event('playing'));
  during(review);
  review.player.currentTime = 10;
  review.player.dispatchEvent(new Event('ended'));
  assert.equal(review.state.naturalPassComplete, true);
  assert.equal(review.state.captionPassComplete, expected);
  return review;
}
const noop = () => {};
const complete = run(noop, noop, true);
complete.track.track.mode = 'disabled';
complete.player.textTracks.dispatchEvent(new Event('change'));
assert.equal(complete.state.captionPassComplete, true);
run(({track}) => { track.readyState = 3; }, noop, false);
run(({track}) => { track.track.cues = []; }, noop, false);
run(({track}) => { track.readyState = 1; }, ({track}) => { track.readyState = 2; }, false);
run(noop, ({track}) => { track.dispatchEvent(new Event('error')); }, false);
run(noop, ({player, track}) => {
  track.track.mode = 'disabled';
  player.textTracks.dispatchEvent(new Event('change'));
  track.track.mode = 'showing';
  player.textTracks.dispatchEvent(new Event('change'));
}, false);
run(noop, ({document}) => {
  document.getElementById('captions').onclick();
  document.getElementById('captions').onclick();
}, false);
run(noop, ({player, track}) => {
  track.track.cues = [];
  player.dispatchEvent(new Event('timeupdate'));
  track.track.cues = [{}];
}, false);
run(noop, ({track}) => { track.readyState = 3; }, false);
""", str(self.output)],
            check=True,
            timeout=10,
        )
