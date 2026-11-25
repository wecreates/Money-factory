"""Build a self-contained review player for an exact unpublished candidate."""

import argparse
import base64
import hashlib
import json
from pathlib import Path

from integrations.content_control.review_package import SHA, no_symlinks, require


def _read_pinned(path, expected, limit):
    path = Path(path).absolute()
    no_symlinks(path)
    require(path.is_file(), 'Regular media or caption file required')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    require(0 < len(data) <= limit, 'Review asset is empty or exceeds the offline player size limit')
    require(isinstance(expected, str) and SHA.fullmatch(expected)
            and hashlib.sha256(data).hexdigest() == expected, 'Review asset SHA-256 mismatch: ' + path.name)
    return data


PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; media-src blob:; script-src 'unsafe-inline'; style-src 'unsafe-inline'">
<title>Private video review</title>
<style>
body {font: 1rem system-ui; color: #f6f8fa; background: #171c23; max-width: 46rem; margin: auto; padding: 1rem;}
video {display: block; width: 100%; max-height: 72vh; background: #090b0d;}
label, p {display: block; margin: .65rem 0;}
textarea {box-sizing: border-box; width: 100%; min-height: 5rem;}
button {font: inherit; padding: .6rem .8rem; margin: .3rem .3rem .3rem 0;}
code {overflow-wrap: anywhere;}
</style></head><body>
<h1>Private video review</h1>
<p>Play the full video with sound. Check captions and seeking, then record what you observed.</p>
<video id="player" controls playsinline preload="metadata"></video>
<p id="status" role="status">Loading the embedded video.</p>
<p><button id="back" type="button">Back 5 seconds</button>
<button id="forward" type="button">Forward 5 seconds</button>
<button id="captions" type="button" aria-pressed="false">Show sidecar captions</button></p>
<p id="caption-status" role="status">The separate caption track starts off so it doesn’t cover captions rendered into the video.</p>
<label for="notes">Playback, sound and caption observations with timestamps</label>
<textarea id="notes" maxlength="4000" placeholder="Example: 00:05–00:08, the second label is readable on my phone."></textarea>
<button id="save" type="button">Save observations</button>
<details><summary>Media identities</summary><p>Video <code>VIDEO_HASH</code></p><p>Captions <code>CAPTION_HASH</code></p></details>
<script id="picture" type="application/octet-stream">VIDEO_BASE64</script>
<script id="sidecar" type="application/octet-stream">CAPTION_BASE64</script>
<script>
const element = id => document.getElementById(id);
const player = element('player');
function embedded(id, type) {
  const bytes = Uint8Array.from(atob(element(id).textContent), value => value.charCodeAt(0));
  return URL.createObjectURL(new Blob([bytes], {type}));
}
player.src = embedded('picture', 'video/mp4');
const track = Object.assign(document.createElement('track'), {
  kind: 'captions', label: 'English sidecar', srclang: 'en', src: embedded('sidecar', 'text/vtt')
});
player.append(track);
track.track.mode = 'hidden';
track.addEventListener('error', () => {element('caption-status').textContent = 'The browser could not load the separate caption track.';});
player.addEventListener('loadedmetadata', () => {element('status').textContent = 'Video loaded. Press play to begin.';});
player.addEventListener('error', () => {element('status').textContent = 'The browser could not play the embedded video.';});
player.addEventListener('ended', () => {element('status').textContent = 'Playback reached the end.';});
function seek(offset) {
  if (Number.isFinite(player.duration)) player.currentTime = Math.max(0, Math.min(player.duration, player.currentTime + offset));
}
element('back').onclick = () => seek(-5);
element('forward').onclick = () => seek(5);
element('captions').onclick = () => {
  const shown = track.track.mode !== 'showing';
  track.track.mode = shown ? 'showing' : 'hidden';
  element('captions').textContent = shown ? 'Hide sidecar captions' : 'Show sidecar captions';
  element('captions').setAttribute('aria-pressed', String(shown));
};
element('save').onclick = () => {
  const notes = element('notes').value.trim();
  if (!notes) {element('status').textContent = 'Enter your observed playback notes before saving.'; return;}
  const played = Array.from({length: player.played.length}, (_, i) => [player.played.start(i), player.played.end(i)]);
  const result = {
    schema_version: 1, status: 'OBSERVATIONS_RECORDED',
    candidate_sha256: 'VIDEO_HASH', caption_sha256: 'CAPTION_HASH',
    recorded_at: new Date().toISOString(), browser: navigator.userAgent,
    playback_intervals: played, browser_duration_seconds: Number.isFinite(player.duration) ? player.duration : null,
    notes, independent_verification: false, full_av_review: false,
    production_approved: false, publication_enabled: false, paid_generation_enabled: false
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2) + '\\n'], {type: 'application/json'}));
  const link = Object.assign(document.createElement('a'), {href: url, download: 'review-VIDEO_PREFIX.json'});
  document.body.append(link);
  link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
</script></body></html>
'''


def build_player(video, captions, output, *, video_sha256, caption_sha256):
    """Embed the original bytes without re-encoding, requests, or package mutation."""
    picture = _read_pinned(video, video_sha256, 32 * 1024 * 1024)
    sidecar = _read_pinned(captions, caption_sha256, 1024 * 1024)
    lines = sidecar.decode('utf-8-sig').splitlines()
    require(lines and lines[0].split(maxsplit=1)[:1] == ['WEBVTT'],
            'WebVTT captions required')
    output = Path(output).absolute()
    no_symlinks(output)
    page = (PAGE.replace('VIDEO_HASH', video_sha256).replace('CAPTION_HASH', caption_sha256)
            .replace('VIDEO_PREFIX', video_sha256[:12])
            .replace('VIDEO_BASE64', base64.b64encode(picture).decode('ascii'))
            .replace('CAPTION_BASE64', base64.b64encode(sidecar).decode('ascii')))
    with output.open('x', encoding='utf-8') as stream:
        stream.write(page)
    return {'candidate_sha256': video_sha256, 'caption_sha256': caption_sha256,
            'player_sha256': hashlib.sha256(page.encode('utf-8')).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--captions', required=True)
    parser.add_argument('--video-sha256', required=True)
    parser.add_argument('--caption-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build_player(args.video, args.captions, args.output,
                                  video_sha256=args.video_sha256, caption_sha256=args.caption_sha256)))
