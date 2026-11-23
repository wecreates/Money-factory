"""Candidate-bound, unpublished review delivery and frame-derived thumbnails.

Thumbnail variants are review choices, not measured CTR winners. This module
never promotes audiovisual, financial-claim or competitor quality approval.
"""
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit
import zipfile

from integrations.content_control.cycle_editorial import normalize_thumbnail_copy
from integrations.content_control.review_package import check_deadline, copy_chunks, copy_file, digest, no_symlinks, require


def editorial_digest(editorial):
    return hashlib.sha256(json.dumps(editorial, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def run(command, timeout=180, *, deadline=None, stderr=False):
    check_deadline(deadline)
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
    try:
        result = subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('Media packaging deadline exhausted') from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'{Path(command[0]).name} failed with exit code {error.returncode}') from error
    check_deadline(deadline)
    return result.stderr if stderr else result.stdout


def declared_layout(editorial, receipt):
    if 'layout' not in editorial and 'layout' not in receipt:
        return None
    require(editorial.get('layout') == receipt.get('layout') == 'landscape',
            'Compiled and rendered landscape layouts must match')
    return 'landscape'


def declared_speaker_label(editorial, receipt):
    key = 'speaker_label_position'
    if key not in editorial and key not in receipt:
        return None
    require(editorial.get(key) == receipt.get(key) == 'above' and 'layout' not in editorial
            and 'layout' not in receipt, 'Compiled and rendered portrait speaker label positions must match')
    return 'above'


def inspect_media(path, *, deadline=None, layout=None, decode=True):
    probe = json.loads(run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                           '-f', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0',
                           '-show_streams', '-show_format', '-of', 'json', str(path)], 30, deadline=deadline))
    videos = [s for s in probe['streams'] if s['codec_type'] == 'video']
    audios = [s for s in probe['streams'] if s['codec_type'] == 'audio']
    require(len(videos) == 1 and len(audios) >= 1, 'One video and an audio stream required')
    duration = float(probe['format']['duration'])
    require(math.isfinite(duration) and 0 < duration <= 1800, 'Invalid media duration')
    width, height = videos[0]['width'], videos[0]['height']
    require(16 <= width <= 8192 and 16 <= height <= 8192, 'Invalid video dimensions')
    if layout == 'landscape':
        require((width, height) == (1280, 720) and len(audios) == 1,
                'Native 1280x720 landscape with one audio stream required')
        require(videos[0].get('sample_aspect_ratio', '1:1') in ('1:1', 'N/A') and
                not any(item.get('rotation', 0) for item in videos[0].get('side_data_list', [])),
                'Rotated/anamorphic sources unsupported')
    media = {'duration_seconds': duration, 'width': width, 'height': height}
    if decode:
        run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-protocol_whitelist', 'file,pipe',
             '-threads', '2', '-f', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0',
             '-i', str(path), '-f', 'null', '-'], deadline=deadline)
        media['decode'] = 'PASS'
    return media


def _link(url):
    require(isinstance(url, str) and len(url) <= 2048, 'Invalid source URL')
    parts = urlsplit(url)
    require(parts.scheme == 'https' and bool(parts.hostname) and not parts.username and not parts.password,
            'Review links must be public HTTPS URLs')
    return html.escape(url, quote=True)


def diagram_thumbnail_crop(editorial, receipt, media):
    """Opt in only to the known picture renderer's diagram region.

    Portrait geometry alone is not evidence of this layout. Unknown renderer
    receipts or scene specifications retain the complete source frame.
    """
    scope = 'Fresh offline speech and original diagram-based picture video; technical verification only.'
    scenes = editorial.get('scenes', [])
    if (receipt.get('scope') == scope and (media.get('width'), media.get('height')) == (720, 1280)
            and scenes and all(isinstance(scene, dict) and isinstance(scene.get('visual_spec'), dict) and
                scene['visual_spec'].get('kind') in {'card', 'receipt', 'balance', 'checklist', 'comparison'}
                for scene in scenes)):
        return (45, 300, 675, 800 if declared_speaker_label(editorial, receipt) else 870)
    return None


def make_thumbnail(frame, target, title, variant, *, source_crop=None):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    colors = [(255, 205, 66), (133, 225, 197), (163, 190, 255)]
    canvas = Image.new('RGB', (1280, 720), '#121820')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 18, 720), fill=colors[variant])
    with Image.open(frame) as image:
        image.load()
        image = image.convert('RGB')
        if source_crop is not None:
            require(len(source_crop) == 4 and all(type(v) is int for v in source_crop), 'Invalid thumbnail crop')
            left, top, right, bottom = source_crop
            require(0 <= left < right <= image.width and 0 <= top < bottom <= image.height,
                    'Thumbnail crop outside source frame')
            image = image.crop(source_crop)
        fitted = ImageOps.contain(image, (640, 680))
        canvas.paste(fitted, (620 + (640 - fitted.width) // 2, (720 - fitted.height) // 2))
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    def font(size):
        return ImageFont.truetype(font_path, size) if Path(font_path).is_file() else ImageFont.load_default(size=size)
    title = ' '.join(title.split())
    require(0 < len(title) <= 180, 'Thumbnail title must contain 1–180 characters')
    chosen = None
    for size in range(72, 23, -2):
        chosen = font(size)
        lines = []
        current = ''
        for word in title.split():
            test = (current + ' ' + word).strip()
            if draw.textbbox((0, 0), test, font=chosen)[2] <= 515:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) * (size + 14) <= 500 and all(draw.textbbox((0, 0), line, font=chosen)[2] <= 515 for line in lines):
            break
    else:
        raise ValueError('Thumbnail title does not fit')
    y = (720 - len(lines) * (size + 14)) // 2
    for line in lines:
        draw.text((56, y), line, fill='white', font=chosen)
        y += size + 14
    canvas.save(target, format='PNG')
    with Image.open(target) as checked:
        checked.verify()
    artwork = hashlib.sha256(str(fitted.size).encode('ascii'))
    artwork.update(fitted.tobytes())
    return artwork.hexdigest()


def capture_thumbnail(output, target, seconds, overlay, variant, crop, deadline):
    raw = output / 'thumbnail-frame.png'
    run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-protocol_whitelist', 'file,pipe',
         '-threads', '2', '-ss', format(seconds, '.6f'), '-f', 'mov', '-i', str(output / 'video.mp4'),
         '-frames:v', '1', '-threads', '1', str(raw)], 60, deadline=deadline)
    if not raw.is_file():
        return None
    artwork = make_thumbnail(raw, target, overlay, variant, source_crop=crop)
    check_deadline(deadline)
    raw.unlink()
    return artwork


def _page(editorial, thumbnails, candidate):
    esc = lambda value: html.escape(str(value), quote=True)
    sources = ''.join('<li><a rel="noreferrer" href="' + _link(s['url']) + '">' + esc(s['id']) +
                      '</a>: ' + esc(s['claim']) + ' <small>Retrieved ' + esc(s['retrieved_at']) +
                      '</small></li>' for s in editorial.get('sources', []))
    references = ''.join('<li><a rel="noreferrer" href="' + _link(r['url']) + '">Reference</a> — ' +
                         esc(r['observation_type']) + ', ' + esc(r['observed_at']) + ': ' +
                         esc('; '.join(r['patterns'])) + '</li>' for r in editorial.get('reference_observations', []))
    script = ''.join('<li><strong>' + esc(s['id']) + '</strong>: ' + esc(s['narration']) +
                     '<p>Visual: ' + esc(s['visual']) + '</p></li>' for s in editorial['scenes'])
    thumbs = ''.join('<figure><img src="' + t['file'] + '" alt="Thumbnail review variant ' + str(i + 1) +
                     '"><figcaption>Variant ' + str(i + 1) + ', source frame at ' +
                     format(t['source_timestamp_seconds'], '.2f') + ' seconds' +
                     (' (diagram crop; omits source headline, scene counter, character and speaker label)'
                      if t.get('framing') == 'diagram_focus' else ' (complete frame)') +
                     (' · Reuses picture from variant ' + str(t['artwork_repeats_variant'])
                      if 'artwork_repeats_variant' in t else '') + '</figcaption></figure>'
                     for i, t in enumerate(thumbnails))
    overlay_note = ('<p>Thumbnail copy: ' + esc(editorial['thumbnail_copy']) + '</p>'
                    if 'thumbnail_copy' in editorial else '')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>CYZOR unpublished review</title><style>body{font:18px system-ui;background:#101722;color:#edf4fa;max-width:1000px;margin:32px auto;padding:0 20px}video{max-height:75vh;max-width:100%;display:block;margin:auto}a{color:#9ed4ff}img{max-width:100%}small{display:block}code{overflow-wrap:anywhere}li{margin:14px 0}figure{margin:24px 0}</style></head><body><h1>''' + esc(editorial['title']) + '''</h1>
<p>Unpublished review candidate. Watch and listen to the complete video. Factual review, audiovisual quality and competitor comparison remain pending. Publishing is disabled.</p>
<video controls playsinline preload="metadata" src="video.mp4"><track kind="captions" src="captions.vtt" srclang="en" label="English"></video>
<p><a href="video.mp4">Video</a> · <a href="captions.vtt">Captions</a> · <a href="editorial.json">Editorial evidence</a> · <a href="automated-review.json">Audio, picture and benchmark diagnostics</a> · <a href="package.json">Verification receipt</a></p><p>Caption timings may be approximate groups distributed over measured speech duration. Check the receipt for independent transcription status; technical media checks do not verify spoken-word accuracy or synchronization.</p>
<h2>Thumbnail choices</h2><p>Frame-derived alternatives for review. No click-through performance has been measured.</p>''' + overlay_note + thumbs + '''<h2>Script and storyboard</h2><ol>''' + script + '''</ol><h2>Research sources</h2><ul>''' + sources + '''</ul><h2>Reference observation scope</h2><ul>''' + references + '''</ul><p>A transcript or metadata observation does not verify a reference video's visuals, pacing or audio.</p><p>Candidate SHA-256: <code>''' + candidate + '</code></p></body></html>\n'


def package_cycle(editorial, render_dir, output, *, deadline=None):
    """Copy one verified candidate into a fresh portable review directory.

    A failed package is removed. Original render outputs are never modified.
    The function does not download reference media or make remote requests.
    """
    check_deadline(deadline)
    require(all(os.environ.get(key, 'false').lower() == 'false'
                for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    require(editorial.get('paid_generation_enabled', False) is False,
            'Paid generation forbidden')
    overlay = editorial['title']
    if 'thumbnail_copy' in editorial:
        overlay = normalize_thumbnail_copy(editorial['thumbnail_copy'])
        require(overlay == editorial['thumbnail_copy'], 'Thumbnail copy is not canonical')
    render_dir, output = Path(render_dir).absolute(), Path(output).absolute()
    no_symlinks(render_dir); no_symlinks(output)
    require(render_dir.is_dir(), 'Render directory required')
    require(not output.exists(), 'Package output already exists')
    require(not output.resolve().is_relative_to(render_dir.resolve()), 'Package must be outside render directory')
    paths = [render_dir / name for name in ('video.mp4', 'captions.vtt', 'render.json')]
    for path in paths:
        require(path.is_file() and not path.is_symlink(), 'Missing regular render file: ' + path.name)
    require(paths[0].stat().st_size <= 256 * 1024 * 1024, 'Video exceeds package size limit')
    require(paths[1].stat().st_size <= 1024 * 1024 and paths[2].stat().st_size <= 1024 * 1024,
            'Render metadata exceeds size limit')
    receipt = json.loads(paths[2].read_text())
    require(receipt.get('technical_status') == 'PASS', 'Technical verification must pass')
    require(all(receipt.get(k) is False for k in ('publication_enabled', 'production_approved', 'full_av_review')) and
            receipt.get('paid_generation_enabled', False) is False,
            'Publication and approval flags must remain false')
    candidate, captions = digest(paths[0], deadline), digest(paths[1], deadline)
    require(candidate == receipt.get('candidate_sha256'), 'Candidate hash mismatch')
    require(captions == receipt.get('caption_sha256'), 'Caption hash mismatch')
    editorial_sha = editorial_digest(editorial)
    require(editorial_sha == receipt.get('editorial_sha256'), 'Editorial hash mismatch')
    require(paths[1].read_text().startswith('WEBVTT'), 'WebVTT captions required')
    render_receipt_sha = digest(paths[2], deadline)
    layout = declared_layout(editorial, receipt)
    speaker_label_position = declared_speaker_label(editorial, receipt)
    media = inspect_media(paths[0], deadline=deadline, layout=layout)
    if speaker_label_position:
        require((media['width'], media['height']) == (720, 1280),
                'Above speaker label requires the 720x1280 portrait renderer')
    # Validate and escape all reference links before creating any output files.
    _page(editorial, [], candidate)
    output.mkdir(parents=True)
    try:
        for source in paths:
            copy_file(source, output / source.name, deadline)
        require(digest(output / 'video.mp4', deadline) == candidate and digest(output / 'captions.vtt', deadline) == captions and
                digest(output / 'render.json', deadline) == render_receipt_sha, 'Copied render changed during packaging')
        thumbnails = []
        source_crop = diagram_thumbnail_crop(editorial, receipt, media)
        artwork_variants = {}
        fallback = output / 'thumbnail-alternative.png'
        for index, fraction in enumerate((0.2, 0.5, 0.8)):
            nominal = timestamp = media['duration_seconds'] * fraction
            filename = 'thumbnail-' + str(index + 1) + '.png'
            target = output / filename
            artwork = capture_thumbnail(output, target, timestamp, overlay, index, source_crop, deadline)
            require(artwork is not None, 'No source frame for nominal thumbnail')
            if artwork in artwork_variants:
                for alternate in (0.9, 0.65, 0.35, 0.1):
                    seconds = media['duration_seconds'] * alternate
                    alternative = capture_thumbnail(output, fallback, seconds, overlay, index, source_crop, deadline)
                    if alternative is not None and alternative not in artwork_variants:
                        fallback.replace(target)
                        timestamp, artwork = seconds, alternative
                        break
                fallback.unlink(missing_ok=True)
            thumbnail = {'file': filename, 'source_timestamp_seconds': timestamp,
                         'framing': 'diagram_focus' if source_crop else 'full_frame',
                         'source_crop_pixels': list(source_crop) if source_crop else None,
                         'source_crop_omissions': ['headline', 'scene counter', 'character', 'speaker label'] if source_crop else [],
                         'source_frame_size': [media['width'], media['height']],
                         'sha256': digest(target, deadline), 'width': 1280, 'height': 720}
            if timestamp != nominal:
                thumbnail['nominal_source_timestamp_seconds'] = nominal
            if artwork in artwork_variants:
                thumbnail['artwork_repeats_variant'] = artwork_variants[artwork]
            artwork_variants.setdefault(artwork, index + 1)
            thumbnails.append(thumbnail)
        (output / 'editorial.json').write_text(json.dumps(editorial, indent=2, sort_keys=True, allow_nan=False) + '\n')
        from integrations.content_control.cycle_av_review import write_automated_review
        write_automated_review(output, candidate, captions, deadline=deadline, media=media)
        (output / 'index.html').write_text(_page(editorial, thumbnails, candidate))
        result = {'schema_version': 1, 'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
                  'created_at': datetime.now(timezone.utc).isoformat(), 'publication_enabled': False,
                  'paid_generation_enabled': False, 'production_approved': False, 'full_av_review': False,
                  'production_ready': False, 'candidate_sha256': candidate, 'caption_sha256': captions,
                  'editorial_sha256': editorial_sha, 'render_receipt_sha256': render_receipt_sha,
                  'media': media, 'thumbnails': thumbnails, 'thumbnail_performance_verified': False,
                  'caption_timing': receipt.get('caption_timing', 'UNSPECIFIED'),
                  'independent_transcription_verified': receipt.get('independent_transcription_verified') is True,
                  'review_required': ['factual_accuracy', 'full_audiovisual_quality', 'competitor_comparison', 'thumbnail_selection'],
                  'files_sha256': {p.name: digest(p, deadline) for p in sorted(output.iterdir()) if p.is_file()}}
        if 'thumbnail_copy' in editorial:
            result['thumbnail_copy'] = overlay
        if layout:
            result['layout'] = layout
        if speaker_label_position:
            result['speaker_label_position'] = speaker_label_position
        (output / 'package.json').write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')
        with zipfile.ZipFile(output / 'review-package.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output.iterdir()):
                if path.name != 'review-package.zip':
                    with path.open('rb') as incoming, archive.open(path.name, 'w') as outgoing:
                        copy_chunks(incoming, outgoing, deadline)
        # The receipt inside the ZIP describes the files; its own identity is returned externally.
        return dict(result, archive_sha256=digest(output / 'review-package.zip', deadline), archive='review-package.zip')
    except BaseException:
        shutil.rmtree(output)
        raise
