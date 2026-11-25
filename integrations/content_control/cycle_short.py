"""Explicit, unpublished portrait excerpts; selection and creative acceptance stay open."""
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.cycle_render import encoded_stream_sha256
from integrations.content_control.cycle_package import diagram_thumbnail_crop, picture_duration
from integrations.content_control.review_package import digest, no_symlinks, require
from integrations.owned_process import owned_process

FLAGS = {k: False for k in ('publication_enabled', 'paid_generation_enabled',
                           'production_approved', 'full_av_review', 'production_ready')}
STAMP = r'(\d{2,}):([0-5]\d):([0-5]\d)\.(\d{3})'
COMPACT_STYLE = 'FontName=DejaVu Sans,FontSize=10,MarginV=4,Outline=1.1,Shadow=0,Alignment=2'
SAFE_CAPTION_STYLE = 'FontName=DejaVu Sans,FontSize=10,MarginV=29,Outline=1.1,Shadow=0,Alignment=2'
SAFE_CAPTION_FILTER = 'scale=648:1152:flags=lanczos,pad=720:1280:36:0:color=0xf7f1e6'


def _seconds(value):
    match = re.fullmatch(STAMP, value)
    require(match is not None, 'Unsupported caption timestamp')
    h, m, s, ms = map(int, match.groups())
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def _stamp(ms):
    seconds, millis = divmod(ms, 1000); minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{millis:03}'


def clip_captions(text, start_ms, end_ms):
    """Accept the pipeline's plain WebVTT only; preserve intersecting cue text."""
    require(text.startswith('WEBVTT\n'), 'Plain WebVTT required')
    cues, truncated = [], []
    prior_end = 0
    for block in re.split(r'\n\s*\n', text.strip())[1:]:
        lines = block.splitlines()
        if lines and re.fullmatch(r'\d+', lines[0]): lines = lines[1:]
        require(len(lines) >= 2 and ' --> ' in lines[0], 'Unsupported caption block')
        parts = lines[0].split(' --> ')
        require(len(parts) == 2, 'Unsupported cue settings')
        a, b = map(_seconds, parts)
        require(prior_end <= a < b, 'Unordered or overlapping captions')
        prior_end = b
        require(all(line.strip() and '-->' not in line for line in lines[1:]), 'Invalid caption text')
        if b <= start_ms or a >= end_ms: continue
        if a < start_ms or b > end_ms: truncated.append(len(cues) + 1)
        cues.append(f'{_stamp(max(a,start_ms)-start_ms)} --> {_stamp(min(b,end_ms)-start_ms)}\n' + '\n'.join(lines[1:]))
    return 'WEBVTT\n\n' + '\n\n'.join(cues) + ('\n' if cues else ''), truncated


def _compact_caption_input(captions):
    require(captions != 'WEBVTT\n\n', 'Compact captions require timed cues')
    # The picture renderer uses html.escape() with quoting enabled. Restore
    # only its quote escapes in the burn input, preserving the bound sidecar
    # and continuing to reject markup, ASS syntax and all other entities.
    plain = captions.replace('&#x27;', "'").replace('&quot;', '"')
    cue_text = [line for block in plain.strip().split('\n\n')[1:] for line in block.splitlines()[1:]]
    require(all(not re.search(r'[<>{}\\&]', line) for line in cue_text),
            'Compact captions require unmarked cue text')
    return plain


def _run(command, deadline, *, cwd=None):
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'Short deadline exhausted')
    with tempfile.TemporaryFile() as stream:
        with owned_process(command, timeout=remaining, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT) as process:
            while process.poll() is None:
                require(time.monotonic() < deadline, 'Short deadline exhausted')
                require(os.fstat(stream.fileno()).st_size <= 1024*1024, 'Media diagnostic output limit')
                time.sleep(.02)
            require(process.returncode == 0, 'Media command failed')
        require(os.fstat(stream.fileno()).st_size <= 1024*1024, 'Media diagnostic output limit')
        stream.seek(0)
        return stream.read()


def _probe(path, deadline, *, include_picture_duration=False):
    data = json.loads(_run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-f','mov',
                           '-show_streams','-show_format','-of','json',str(path)], deadline))
    videos = [s for s in data['streams'] if s['codec_type']=='video']
    audio = [s for s in data['streams'] if s['codec_type']=='audio']
    require(len(videos)==1 and len(audio)==1, 'Exactly one video and audio stream required')
    v=videos[0]; width,height=v['width'],v['height']
    require(16 <= width <= 8192 and 16 <= height <= 8192 and width*16==height*9,
            'Existing 9:16 portrait framing required; no automatic crop')
    require(v.get('sample_aspect_ratio','1:1') in ('1:1','N/A') and
            not any(s.get('rotation',0) for s in v.get('side_data_list',[])), 'Rotated/anamorphic sources unsupported')
    duration=float(data['format']['duration'])
    require(math.isfinite(duration) and 0 < duration <= 1800, 'Invalid media duration')
    media = {'width':width,'height':height,'duration_seconds':duration}
    if include_picture_duration:
        media['picture_duration_seconds'] = picture_duration(v)
    return media


def decoded_picture_sha256(media, deadline):
    """Hash the ordered decoded RGB frames, not only the MP4 container bytes."""
    output = _run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-threads', '2',
                   '-i', str(media), '-map', '0:v:0', '-an', '-c:v', 'rawvideo',
                   '-pix_fmt', 'rgb24', '-f', 'hash', '-hash', 'sha256', '-'], deadline)
    match = re.fullmatch(rb'SHA256=([0-9a-f]{64})\s*', output)
    require(match is not None, 'Decoded picture hash evidence is invalid')
    return match.group(1).decode()


def media_identities(media, output, deadline):
    """Bind encoded video/audio packets and ordered decoded picture frames."""
    with tempfile.TemporaryDirectory(prefix='.identity-', dir=output) as identity_directory:
        identity = Path(identity_directory)
        streams = {
            'video': encoded_stream_sha256(media, 'v:0', identity/'video.log', deadline),
            'audio': encoded_stream_sha256(media, 'a:0', identity/'audio.log', deadline),
        }
        picture = decoded_picture_sha256(media, deadline)
    return streams, picture


def _preview_html(bindings, *, burned_captions):
    if burned_captions:
        track = ''
        caption_note = 'Captions are already visible in the video. The WebVTT file is available for reference.'
    else:
        track = '<track kind="captions" src="captions.vtt" srclang="en" label="English" default>'
        caption_note = 'Use the video player’s caption control to view the WebVTT captions.'
    fingerprints = ''.join(f'<dt>{label}</dt><dd><code>{escape(bindings[key])}</code></dd>'
                           for label, key in (
                               ('Video', 'candidate_sha256'), ('Captions', 'caption_sha256'),
                               ('Automated review', 'automated_review_sha256'),
                               ('Parent video', 'parent_candidate_sha256'), ('Parent cycle', 'parent_cycle_sha256'),
                               ('Parent captions', 'source_caption_sha256')))
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; media-src 'self'; style-src 'unsafe-inline'">
<title>Unpublished Short review</title>
<style>
body {{ font: 17px system-ui; background: #101722; color: #f0f4fa; max-width: 640px; margin: 1rem auto; padding: 0 1rem; }}
video {{ display: block; width: 100%; max-height: 70vh; background: #080c12; }}
a {{ color: #9fd3ff; }}
dd {{ margin: 0 0 .6rem; overflow-wrap: anywhere; }}
</style>
<main>
<h1>Unpublished Short review</h1>
<video controls playsinline preload="metadata" src="video.mp4">
{track}
</video>
<p>{caption_note}</p>
<p><a href="video.mp4">Open video</a> · <a href="captions.vtt" download>Download captions</a> ·
<a href="automated-review.json">Review diagnostics</a> · <a href="short.json">Short receipt</a></p>
<p>Watch and listen to the complete excerpt before recording a review. Publishing is disabled.</p>
<details><summary>SHA-256 identities</summary><dl>{fingerprints}</dl></details>
</main>
</html>
"""


def make_short(cycle_dir, output, *, start, end, timeout=180, hide_source_counter=False,
               compact_captions=False, caption_safe_area=False):
    require(type(hide_source_counter) is bool, 'hide_source_counter must be boolean')
    require(type(compact_captions) is bool, 'compact_captions must be boolean')
    require(type(caption_safe_area) is bool, 'caption_safe_area must be boolean')
    require(not caption_safe_area or compact_captions,
            'caption_safe_area requires compact_captions')
    require(type(timeout) is int and 10 <= timeout <= 600, 'Timeout must be 10..600 seconds')
    require(all(type(v) in (int,float) and math.isfinite(v) for v in (start,end)) and
            0 <= start < end and end-start <= 60, 'Explicit finite interval of at most 60 seconds required')
    start_ms,end_ms=round(start*1000),round(end*1000)
    require(start_ms < end_ms, 'Interval must span at least one millisecond')
    require(all(os.environ.get(k,'false').lower()=='false' for k in
                ('PUBLICATION_ENABLED','PAID_GENERATION_ENABLED')), 'Publishing and paid generation must stay disabled')
    root=Path(os.path.abspath(cycle_dir)); output=Path(os.path.abspath(output))
    no_symlinks(root);no_symlinks(output)
    require(not output.exists() and not output.is_relative_to(root), 'Fresh output outside source cycle required')
    deadline=time.monotonic()+timeout
    snapshot=inspect_cycle(root)
    media=root/'delivery/video.mp4'; captions=root/'delivery/captions.vtt'
    source=_probe(media,deadline)
    counter_filter=[]
    counter_action={'action':'preserve'}
    if hide_source_counter or compact_captions:
        # inspect_cycle has already verified this exact receipt and editorial.
        render=json.loads((root/'delivery/render.json').read_text())
        require(diagram_thumbnail_crop(snapshot['editorial'],render,source) is not None,
                'Counter removal and compact captions require the known 720x1280 picture-renderer layout')
    if hide_source_counter:
        counter_filter=['-vf','drawbox=x=570:y=40:w=110:h=45:color=0xf7f1e6:t=fill']
        counter_action={'action':'hide_source_scene_counter','rectangle_xywh':[570,40,110,45],
                        'fill_rgb':'#f7f1e6',
                        'scope':'Known renderer scene-counter region only; no reframing or automatic media cleanup.'}
    require(end <= source['duration_seconds'] and end_ms/1000 <= source['duration_seconds'], 'Interval exceeds source media')
    require(captions.stat().st_size <= 1024*1024, 'Caption input oversized')
    clipped,boundary=clip_captions(captions.read_text(),start_ms,end_ms)
    if compact_captions:
        _compact_caption_input(clipped)
    output.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':1,'status':'BLOCKED','technical_status':'PENDING',**FLAGS,
             'source_counter':counter_action,'tool_sha256':digest(Path(__file__)),
             'parent_candidate_sha256':snapshot['candidate_sha256'],
             'parent_cycle_sha256':snapshot['files_sha256']['cycle.json'],
             'source_caption_sha256':digest(captions),'start_seconds':start_ms/1000,'end_seconds':end_ms/1000,
             'boundary_cue_numbers':boundary,'selection_scope':'Explicit supplied time bounds; not automatic editorial selection.',
             'caption_scope':'Intersecting source cues clipped/rebased; whole cue text retained even at cut boundaries. Review boundary words against audio.',
             'scope':'Unreviewed portrait excerpt; no long-form, creative, listening, phone or publishing acceptance.',
             'started_at':datetime.now(timezone.utc).isoformat()}
    preview = output/'index.html'
    try:
        working = tempfile.TemporaryDirectory(prefix='.compact-', dir=output) if compact_captions else nullcontext(output)
        with working as directory:
            stage = Path(directory)
            encoded = stage / ('clean.mp4' if compact_captions else 'video.mp4')
            _run(['ffmpeg','-v','error','-xerror','-nostdin','-n','-protocol_whitelist','file,pipe','-threads','2',
                  '-f','mov','-i',str(media),'-ss',str(start_ms/1000),'-t',str((end_ms-start_ms)/1000),
                  '-map','0:v:0','-map','0:a:0','-map_metadata','-1',*counter_filter,'-c:v','libx264','-threads','2',
                  '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart','-fs',str(256*1024*1024),str(encoded)],deadline)
            actual = _probe(encoded, deadline, include_picture_duration=True)
            picture = actual['picture_duration_seconds']
            container = Fraction(str(actual['duration_seconds']))
            receipt.update(encoded_picture_duration_seconds=float(picture),
                           encoded_container_duration_seconds=actual['duration_seconds'])
            require(picture <= 60 and container <= 60, 'Encoded video exceeds the 60-second Short limit')
            requested = Fraction(end_ms - start_ms, 1000)
            require(all(abs(observed - requested) <= Fraction(1, 10) for observed in (picture, container)),
                    'Encoded picture or container duration differs from requested interval')
            require(actual['width']==source['width'] and actual['height']==source['height'],'Framing changed')
            caption_end_ms = min(end_ms, start_ms + math.floor(min(picture, container) * 1000))
            require(caption_end_ms > start_ms, 'Encoded excerpt must span at least one caption millisecond')
            clipped, boundary = clip_captions(captions.read_text(), start_ms, caption_end_ms)
            if compact_captions:
                require(clipped != 'WEBVTT\n\n', 'No captions remain within the encoded excerpt')
                (stage/'captions.vtt').write_text(_compact_caption_input(clipped))
                caption_style = SAFE_CAPTION_STYLE if caption_safe_area else COMPACT_STYLE
                picture_filter = f'{SAFE_CAPTION_FILTER},' if caption_safe_area else ''
                _run(['ffmpeg','-v','error','-xerror','-nostdin','-n','-protocol_whitelist','file,pipe','-threads','2',
                      '-f','mov','-i','clean.mp4','-map','0:v:0','-map','0:a:0','-map_metadata','-1',
                      '-vf',f"{picture_filter}subtitles=filename=captions.vtt:force_style='{caption_style}'",'-filter_threads','1',
                      '-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',
                      '-fs',str(256*1024*1024),str(output/'video.mp4')],deadline,cwd=stage)
                require(_probe(output/'video.mp4', deadline, include_picture_duration=True) == actual,
                        'Caption burn changed media framing or duration')
                receipt['caption_overlay'] = {
                    'style': caption_style,
                    'audio_mode': 'stream_copy_from_excerpt',
                    'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
                }
                if caption_safe_area:
                    receipt['caption_overlay']['picture_layout'] = {
                        'mode': 'scaled_picture_safe_caption_area_v1',
                        'source_scale_percent': 90,
                        'scaled_picture_size': [648, 1152],
                        'canvas_size': [720, 1280],
                        'picture_offset': [36, 0],
                        'background_rgb': '#f7f1e6',
                        'caption_bottom_clearance_target_pixels': 125,
                    }
        _run(['ffmpeg','-v','error','-xerror','-nostdin','-threads','2','-i',str(output/'video.mp4'),'-f','null','-'],deadline)
        receipt['boundary_cue_numbers'] = boundary
        (output/'captions.vtt').write_text(clipped)
        require(inspect_cycle(root)==snapshot,'Source cycle changed while clipping')
        candidate = digest(output/'video.mp4', deadline)
        caption_sha = digest(output/'captions.vtt', deadline)
        stream_hashes, picture_sha = media_identities(output/'video.mp4', output, deadline)
        from integrations.content_control.cycle_av_review import read_automated_review, write_automated_review
        actual.pop('picture_duration_seconds')
        write_automated_review(output, candidate, caption_sha, deadline=deadline, media=actual)
        review = read_automated_review(output/'automated-review.json', candidate, caption_sha)
        require(digest(output/'video.mp4', deadline) == candidate
                and digest(output/'captions.vtt', deadline) == caption_sha, 'Short media or captions changed before preview')
        bindings = {'candidate_sha256': candidate, 'caption_sha256': caption_sha,
                    'automated_review_sha256': hashlib.sha256(review).hexdigest()}
        with preview.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(_preview_html(receipt | bindings, burned_captions=compact_captions))
        preview_sha = digest(preview, deadline)
        receipt.update(status='AWAITING_REVIEW',technical_status='PASS',media=actual,
                       **bindings, preview_sha256=preview_sha,
                       encoded_streams_sha256=stream_hashes,
                       decoded_picture_sha256=picture_sha,
                       preview_caption_mode='burned' if compact_captions else 'sidecar')
    except (OSError,ValueError,RuntimeError,TimeoutError,subprocess.SubprocessError,KeyError,TypeError) as error:
        preview.unlink(missing_ok=True)
        receipt['reason']=str(error)
    finally:
        receipt['finished_at']=datetime.now(timezone.utc).isoformat()
        try:
            (output/'short.json').write_text(json.dumps(receipt,indent=2,sort_keys=True,allow_nan=False)+'\n')
        except OSError:
            preview.unlink(missing_ok=True)
            raise
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--start',type=float,required=True);parser.add_argument('--end',type=float,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--hide-source-counter',action='store_true',
                        help='Hide only the known picture renderer scene-counter region; unknown layouts are rejected.')
    parser.add_argument('--compact-captions',action='store_true',
                        help='Burn compact captions into a separate excerpt of the known picture renderer.')
    parser.add_argument('--caption-safe-area',action='store_true',
                        help='Scale the known picture renderer to 90%% and target at least 125px bottom caption clearance.')
    a=parser.parse_args();result=make_short(a.cycle_dir,a.output,start=a.start,end=a.end,timeout=a.timeout,
                                        hide_source_counter=a.hide_source_counter,compact_captions=a.compact_captions,
                                        caption_safe_area=a.caption_safe_area)
    print(json.dumps(result,indent=2));return 0 if result['status']=='AWAITING_REVIEW' else 2


if __name__=='__main__': raise SystemExit(main())
