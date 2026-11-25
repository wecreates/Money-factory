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
textarea, input, select {box-sizing: border-box; width: 100%; font: inherit; padding: .45rem;}
textarea {min-height: 5rem;}
fieldset {margin: .8rem 0; border: 1px solid #66717f;}
fieldset label {display: inline-block; margin-right: 1rem;}
fieldset input {width: auto;}
button {font: inherit; padding: .6rem .8rem; margin: .3rem .3rem .3rem 0;}
code {overflow-wrap: anywhere;}
</style></head><body>
<h1>Private video review</h1>
<p>Play the full video with sound. Check captions and seeking, then record what you observed.</p>
<video id="player" playsinline preload="metadata"></video>
<p id="status" role="status">Verifying the embedded media identities.</p>
<p><button id="back" type="button">Back 5 seconds</button>
<button id="forward" type="button">Forward 5 seconds</button>
<button id="reset" type="button">Reset natural pass</button>
<button id="captions" type="button" aria-pressed="false">Show sidecar captions</button></p>
<p id="caption-status" role="status">The separate caption track starts off so it doesn’t cover captions rendered into the video.</p>
<label for="reviewer">Reviewer label</label><input id="reviewer" maxlength="200" autocomplete="off">
<fieldset><legend>Reviewer roles</legend>
<label><input type="checkbox" name="role" value="watcher"> Watcher</label>
<label><input type="checkbox" name="role" value="listener"> Listener</label>
<label><input type="checkbox" name="role" value="reviewer"> Reviewer</label></fieldset>
<label for="round">Review round</label><select id="round"><option value="initial">Initial</option><option value="post_repair">Post-repair</option></select>
<label for="audio-output">Audio output</label><select id="audio-output"><option value="">Select</option><option value="headphones">Headphones</option><option value="speakers">Speakers</option><option value="phone">Phone</option></select>
<label for="environment">Device and listening environment</label><textarea id="environment" maxlength="1000"></textarea>
<fieldset><legend>Explicit reviewer attestations</legend>
<label><input id="watched" type="checkbox"> Watched every interval</label>
<label><input id="listened" type="checkbox"> Listened to every interval on audible output</label>
<label><input id="voice" type="checkbox"> Checked voice, naturalness and pronunciation</label>
<label><input id="mix" type="checkbox"> Checked music, effects, mix and transitions</label>
<label><input id="picture-check" type="checkbox"> Checked movement, typography and captions</label></fieldset>
<label for="disposition">Disposition</label><select id="disposition"><option value="">Select</option><option value="no_blocker_seen">No blocker seen</option><option value="repair_required">Repair required</option><option value="blocked">Blocked</option></select>
<label for="summary">Review summary</label><textarea id="summary" maxlength="4000"></textarea>
<label for="findings">Structured findings (JSON array)</label>
<textarea id="findings" maxlength="20000" spellcheck="false">[]</textarea>
<p>Each finding uses start_seconds, end_seconds, category, severity, observation, requested_repair and resolution_state.</p>
<label for="parent-hash">Parent video SHA-256 (optional)</label><input id="parent-hash" maxlength="64" spellcheck="false">
<label for="supersedes-hash">Superseded review record SHA-256 (optional)</label><input id="supersedes-hash" maxlength="64" spellcheck="false">
<button id="save" type="button" disabled>Save review evidence</button>
<details><summary>Media identities</summary><p>Video <code>VIDEO_HASH</code></p><p>Captions <code>CAPTION_HASH</code></p></details>
<script id="picture" type="application/octet-stream">VIDEO_BASE64</script>
<script id="sidecar" type="application/octet-stream">CAPTION_BASE64</script>
<script>
const element = id => document.getElementById(id);
const player = element('player');
const EXPECTED_VIDEO = 'VIDEO_HASH';
const EXPECTED_CAPTIONS = 'CAPTION_HASH';
const SHA = /^[0-9a-f]{64}$/;
const categories = new Set(['pronunciation','naturalness','character_voice','intelligibility','timing','music_sfx','mix','caption_sync','movement_staging','typography_legibility','transition_payoff']);
const state = {identityVerified: false, naturalPassComplete: false, captionPassComplete: false,
  active: false, valid: false, captionValid: false, startedAt: null, endedAt: null,
  events: [], invalidations: []};
function bytes(id) {
  return Uint8Array.from(atob(element(id).textContent), value => value.charCodeAt(0));
}
async function digest(data) {
  const value = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(value), byte => byte.toString(16).padStart(2, '0')).join('');
}
function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + stable(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
function logEvent(type, detail={}) {
  state.events.push({type, at: new Date().toISOString(), playback_seconds: Number.isFinite(player.currentTime) ? player.currentTime : null, ...detail});
}
function invalidate(reason) {
  if (state.active && state.valid) {
    state.valid = false; state.captionValid = false; state.invalidations.push(reason);
    logEvent('pass_invalidated', {reason});
    element('status').textContent = 'Natural pass invalidated: ' + reason + '. Reset at time zero to try again.';
  }
}
function objectUrl(data, type) {return URL.createObjectURL(new Blob([data], {type}));}
const pictureBytes = bytes('picture');
const captionBytes = bytes('sidecar');
const track = Object.assign(document.createElement('track'), {
  kind: 'captions', label: 'English sidecar', srclang: 'en'
});
player.append(track);
track.track.mode = 'hidden';
track.addEventListener('error', () => {element('caption-status').textContent = 'The browser could not load the separate caption track.';});
Promise.all([digest(pictureBytes), digest(captionBytes)]).then(([videoHash, captionHash]) => {
  if (videoHash !== EXPECTED_VIDEO || captionHash !== EXPECTED_CAPTIONS) throw new Error('embedded media identity mismatch');
  state.identityVerified = true;
  player.src = objectUrl(pictureBytes, 'video/mp4');
  track.src = objectUrl(captionBytes, 'text/vtt');
  player.controls = true; element('save').disabled = false;
  logEvent('identities_verified');
}).catch(error => {
  element('status').textContent = 'Identity verification failed; review and export remain disabled.';
  logEvent('identity_failure', {reason: String(error)});
});
player.addEventListener('loadedmetadata', () => {element('status').textContent = 'Video loaded and identities verified. Start at time zero for a natural pass.'; logEvent('loadedmetadata', {duration_seconds: player.duration});});
player.addEventListener('error', () => {invalidate('media error'); element('status').textContent = 'The browser could not play the embedded video.';});
player.addEventListener('playing', () => {
  if (!state.active) {
    state.active = true; state.valid = player.currentTime <= .25 && player.playbackRate === 1 && !player.muted && player.volume > 0 && !document.hidden;
    state.captionValid = track.track.mode === 'showing';
    state.startedAt = new Date().toISOString();
    if (!state.valid) state.invalidations.push('pass did not start audibly, visibly, at 1x near time zero');
    logEvent('natural_pass_started', {valid: state.valid, caption_showing: state.captionValid});
  } else logEvent('playback_resumed');
});
player.addEventListener('pause', () => {if (!player.ended) logEvent('playback_paused');});
player.addEventListener('seeking', () => invalidate('seeking'));
player.addEventListener('ratechange', () => {if (player.playbackRate !== 1) invalidate('playback rate changed');});
player.addEventListener('volumechange', () => {if (player.muted || player.volume <= 0) invalidate('audio muted or volume zero');});
document.addEventListener('visibilitychange', () => {if (document.hidden && !player.paused) invalidate('review tab hidden during playback');});
player.addEventListener('ended', () => {
  state.endedAt = new Date().toISOString();
  state.naturalPassComplete = state.active && state.valid && Number.isFinite(player.duration) && player.currentTime >= player.duration - .25;
  state.captionPassComplete = state.naturalPassComplete && state.captionValid;
  logEvent('playback_ended', {natural_pass_complete: state.naturalPassComplete, caption_pass_complete: state.captionPassComplete});
  element('status').textContent = state.naturalPassComplete ? 'Natural playback pass completed.' : 'Playback ended without a valid natural pass.';
});
function seek(offset) {
  if (Number.isFinite(player.duration)) player.currentTime = Math.max(0, Math.min(player.duration, player.currentTime + offset));
}
element('back').onclick = () => seek(-5);
element('forward').onclick = () => seek(5);
element('reset').onclick = () => {
  player.pause(); player.currentTime = 0; player.playbackRate = 1; player.muted = false;
  state.naturalPassComplete = false; state.captionPassComplete = false; state.active = false; state.valid = false;
  state.captionValid = false; state.startedAt = null; state.endedAt = null; state.invalidations = [];
  state.events = [];
  logEvent('natural_pass_reset'); element('status').textContent = 'Natural pass reset at time zero.';
};
element('captions').onclick = () => {
  const shown = track.track.mode !== 'showing';
  track.track.mode = shown ? 'showing' : 'hidden';
  if (state.active && !shown) state.captionValid = false;
  logEvent('caption_mode_changed', {mode: track.track.mode});
  element('captions').textContent = shown ? 'Hide sidecar captions' : 'Show sidecar captions';
  element('captions').setAttribute('aria-pressed', String(shown));
};
function checked(id) {return element(id).checked;}
function validateFindings(value) {
  if (!Array.isArray(value)) throw new Error('Findings must be a JSON array.');
  for (const finding of value) {
    if (!finding || typeof finding !== 'object' || Array.isArray(finding)) throw new Error('Each finding must be an object.');
    if (!Number.isFinite(finding.start_seconds) || !Number.isFinite(finding.end_seconds) || finding.start_seconds < 0 || finding.start_seconds > finding.end_seconds || (Number.isFinite(player.duration) && finding.end_seconds > player.duration + .25)) throw new Error('Finding intervals must be finite, ordered and within the video.');
    if (!categories.has(finding.category) || !['note','blocker'].includes(finding.severity) || typeof finding.observation !== 'string' || !finding.observation.trim() || !['open','resolved','not_applicable'].includes(finding.resolution_state)) throw new Error('A finding has an invalid category, severity, observation or resolution state.');
    if (finding.severity === 'blocker' && (typeof finding.requested_repair !== 'string' || !finding.requested_repair.trim())) throw new Error('Blocker findings require a requested repair.');
  }
  return value;
}
element('save').onclick = async () => {
  try {
  if (!state.identityVerified) throw new Error('Exact media identities are not verified.');
  const reviewer = element('reviewer').value.trim();
  const roles = Array.from(document.querySelectorAll('input[name="role"]:checked'), input => input.value);
  const environment = element('environment').value.trim();
  const disposition = element('disposition').value;
  const summary = element('summary').value.trim();
  if (!reviewer || !roles.length || !element('audio-output').value || !environment || !disposition || !summary) throw new Error('Complete reviewer, role, audio, environment, disposition and summary fields.');
  const findings = validateFindings(JSON.parse(element('findings').value));
  if (findings.some(item => item.severity === 'blocker') && disposition === 'no_blocker_seen') throw new Error('A blocker finding requires repair or blocked disposition.');
  const parent = element('parent-hash').value.trim();
  const supersedes = element('supersedes-hash').value.trim();
  if ((parent && !SHA.test(parent)) || (supersedes && !SHA.test(supersedes))) throw new Error('Optional lineage values must be lowercase SHA-256.');
  if (element('round').value === 'post_repair' && (!parent || parent === EXPECTED_VIDEO || !supersedes)) throw new Error('Post-repair review requires a different parent video and a superseded review record SHA-256.');
  if (element('round').value === 'initial' && (parent || supersedes)) throw new Error('Initial review cannot claim revision lineage.');
  const played = Array.from({length: player.played.length}, (_, i) => [player.played.start(i), player.played.end(i)]);
  const attestation = {reviewer, roles, review_round: element('round').value, audio_output: element('audio-output').value,
    device_environment: environment, disposition, summary,
    watched_every_interval: checked('watched'), listened_every_interval: checked('listened'), checked_voice: checked('voice'),
    checked_mix: checked('mix'), checked_picture_and_captions: checked('picture-check')};
  const fullAttestation = attestation.watched_every_interval && attestation.listened_every_interval && attestation.checked_voice && attestation.checked_mix && attestation.checked_picture_and_captions;
  const complete = state.naturalPassComplete && fullAttestation;
  const result = {
    schema_version: 2, status: complete ? 'FULL_REVIEW_RECORDED' : 'OBSERVATIONS_RECORDED',
    candidate_sha256: EXPECTED_VIDEO, caption_sha256: EXPECTED_CAPTIONS,
    recorded_at: new Date().toISOString(), parent_video_sha256: parent || null, supersedes_record_sha256: supersedes || null,
    machine_observation: {identity_verified: true, browser: navigator.userAgent, viewport: [innerWidth, innerHeight], timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      browser_duration_seconds: Number.isFinite(player.duration) ? player.duration : null, natural_pass_complete: state.naturalPassComplete,
      caption_pass_complete: state.captionPassComplete, started_at: state.startedAt, ended_at: state.endedAt,
      playback_intervals: played, events: state.events, invalidations: state.invalidations,
      caption_mode: track.track.mode, caption_cue_count: track.track.cues ? track.track.cues.length : null},
    reviewer_attestation: attestation, findings,
    reviewer_attested_full_watch_listen: attestation.watched_every_interval && attestation.listened_every_interval,
    review_coverage_complete: complete,
    independent_acceptance: false, full_av_acceptance: false, production_approved: false,
    publication_enabled: false, paid_generation_enabled: false, competitor_comparison_included: false,
    physical_phone_verified: false
  };
  result.record_sha256 = await digest(new TextEncoder().encode(stable(result)));
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2) + '\\n'], {type: 'application/json'}));
  const link = Object.assign(document.createElement('a'), {href: url, download: 'review-VIDEO_PREFIX.json'});
  document.body.append(link);
  link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  element('status').textContent = complete ? 'Full supplied review evidence saved; no independent acceptance was granted.' : 'Partial or blocked review evidence saved; no acceptance was granted.';
  } catch (error) {element('status').textContent = error.message || String(error);}
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
