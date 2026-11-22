"""Render fresh editorial scenes with offline Kokoro and original picture panels.

Technical completion leaves creative, factual and listening review open. This
renderer never changes canonical Episode 1 inputs or calls a publishing API.
"""
import argparse
from datetime import datetime, timezone
from collections import Counter
import difflib
import hashlib
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time
import wave

VOICE_ASSIGNMENTS = {'dave': 'am_fenrir', 'points_monk': 'am_michael', 'narrator': 'am_adam'}
KINDS = {'card', 'receipt', 'balance', 'checklist', 'comparison'}
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
ASR_REPOSITORY = 'Systran/faster-whisper-base.en'
ASR_REVISION = '3d3d5dee26484f91867d81cb899cfcf72b96be6c'
ASR_ASSETS = {
    'config.json': (2227, 'f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb'),
    'model.bin': (145216508, '2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef'),
    'tokenizer.json': (2128466, '929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df'),
    'vocabulary.txt': (422309, 'ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf'),
}
MOTION_FRAMES = 24
MOTION_FPS = 8
MOTION_SCOPE = 'Deterministic three-second arm-gesture loop; static diagrams and typography. No lip sync or full character animation.'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def editorial_digest(editorial):
    return hashlib.sha256(json.dumps(editorial, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')


def validate(editorial):
    if not isinstance(editorial, dict) or editorial.get('publication_enabled') is not False:
        raise ValueError('Explicit disabled publication required')
    if any(editorial.get(key) is not False for key in ('production_approved', 'full_av_review')):
        raise ValueError('Explicit false production and audiovisual approval required')
    if editorial.get('paid_generation_enabled', False) is not False:
        raise ValueError('Paid generation forbidden')
    scenes = editorial.get('scenes')
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 30:
        raise ValueError('One to thirty scenes required')
    seen = set()
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get('id'), str) or scene['id'] in seen:
            raise ValueError('Unique scene IDs required')
        seen.add(scene['id'])
        for key, limit in [('narration', 1000), ('visual', 1000)]:
            if not isinstance(scene.get(key), str) or not 1 <= len(scene[key].strip()) <= limit:
                raise ValueError('Invalid scene ' + key)
        if scene.get('speaker', 'narrator') not in VOICE_ASSIGNMENTS:
            raise ValueError('Unsupported voice assignment')
        spec = scene.get('visual_spec', {})
        if not isinstance(spec, dict) or spec.get('kind', 'card') not in KINDS:
            raise ValueError('Invalid visual specification')
        if 'headline' in spec and (not isinstance(spec['headline'], str) or len(spec['headline']) > 60):
            raise ValueError('Invalid headline')
        for key, limit in [('labels', 50), ('values', 30)]:
            values = spec.get(key, [])
            if not isinstance(values, list) or len(values) > 4 or any(not isinstance(v, str) or len(v) > limit for v in values):
                raise ValueError('Invalid visual ' + key)
    return scenes


def run(command, log, deadline, env=None):
    from integrations.owned_process import owned_process
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Cycle render deadline exceeded')
    with Path(log).open('wb') as stream:
        with owned_process(list(map(str, command)), timeout=remaining, stdout=stream,
                           stderr=subprocess.STDOUT, env=env) as process:
            code = process.wait(timeout=remaining + 5)
    if code:
        raise RuntimeError(f'{Path(command[0]).name} failed; see {Path(log).name}')


def synthesize(editorial, output, voice_root):
    """Runs in the isolated, pinned Kokoro runtime, with network denied."""
    scenes = validate(editorial)
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    def no_network(*args, **kwargs):
        raise RuntimeError('Network disabled during voice synthesis')
    socket.socket.connect = no_network
    generator = Path(voice_root).resolve() / 'scripts/v2_free_voice.py'
    spec = importlib.util.spec_from_file_location('cyzor_pinned_voice', generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.VOICE_ASSIGNMENTS != VOICE_ASSIGNMENTS:
        raise ValueError('Voice assignment changed')
    generator_hash = digest(generator)
    synth = module.local_synthesizer()  # Verifies all five immutable model files.
    clips = []
    for index, scene in enumerate(scenes):
        speaker = scene.get('speaker', 'narrator')
        samples, rate = synth(scene['narration'], VOICE_ASSIGNMENTS[speaker], 1.0)
        if rate != 24000 or not 0 < len(samples) <= rate * 90:
            raise ValueError('Invalid voice output length')
        if any(not math.isfinite(float(v)) or abs(float(v)) > 1 for v in samples):
            raise ValueError('Invalid voice samples')
        rms = math.sqrt(sum(float(v) ** 2 for v in samples) / len(samples))
        if rms < .001:
            raise ValueError('Silent generated narration')
        path = output / f'voice-{index:02d}.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            wav.writeframes(struct.pack('<' + 'h' * len(samples), *[round(float(v) * 32767) for v in samples]))
        clips.append({'scene_id': scene['id'], 'speaker': speaker, 'voice_id': VOICE_ASSIGNMENTS[speaker],
                      'file': path.name, 'audio_sha256': digest(path), 'duration_seconds': len(samples) / rate,
                      'text_sha256': hashlib.sha256(scene['narration'].encode()).hexdigest(), 'rms': rms})
    if digest(generator) != generator_hash:
        raise ValueError('Voice generator changed during synthesis')
    write(output / 'voice.json', {'status': 'GENERATED_PENDING_LISTENING_REVIEW', 'clips': clips,
          'generator_sha256': generator_hash, **module.model_identity(), 'publication_enabled': False,
          'production_approved': False, 'full_av_review': False, 'voice_assignments': VOICE_ASSIGNMENTS})


def draw_panel(scene, path, index, count, phase=0.0):
    """Fresh diagram and character composition with a bounded periodic gesture.

    Phase is a fraction of one loop. Zero preserves the representative pose;
    only the arms move, leaving labels, diagrams and character identity fixed.
    """
    if type(phase) not in (int, float) or not math.isfinite(phase):
        raise ValueError('Finite numeric motion phase required')
    gesture = math.sin(2 * math.pi * (phase % 1.0)) * .18
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (720, 1280), '#f7f1e6')
    draw = ImageDraw.Draw(image)
    ink, accent = '#141414', '#007f89'
    def font(size):
        return ImageFont.truetype(FONT, size)
    def wrapped(text, y, size=38, width=600, color=ink, max_lines=4):
        f = font(size)
        words, lines, current = str(text).split(), [], ''
        for word in words:
            trial = (current + ' ' + word).strip()
            if draw.textlength(trial, font=f) > width and current:
                lines.append(current); current = word
            else:
                current = trial
        if current: lines.append(current)
        if len(lines) > max_lines or any(draw.textlength(line, font=f) > width for line in lines):
            raise ValueError('Visual text exceeds readable panel bounds')
        for line in lines:
            draw.text((360, y), line, font=f, fill=color, anchor='mt')
            y += size + 12
        return y
    spec = scene.get('visual_spec', {})
    headline = spec.get('headline') or scene['visual'][:60]
    wrapped(headline, 105, size=42, max_lines=3)
    kind = spec.get('kind', 'card')
    labels, values = spec.get('labels', []), spec.get('values', [])
    if kind == 'balance':
        draw.line((360, 390, 360, 750), fill=ink, width=10)
        draw.line((130, 450, 590, 450), fill=ink, width=10)
        draw.line((280, 750, 440, 750), fill=ink, width=12)
        for x in (180, 540):
            draw.line((x, 450, x-70, 590), fill=ink, width=5)
            draw.line((x, 450, x+70, 590), fill=ink, width=5)
            draw.arc((x-80, 535, x+80, 645), 0, 180, fill=accent, width=9)
        wrapped('  |  '.join(values[:2] or labels[:2]), 660, size=36, max_lines=2)
    elif kind == 'comparison':
        for i, x in enumerate((60, 375)):
            draw.rounded_rectangle((x, 340, x+285, 710), radius=24, outline=accent if i else ink, width=6)
            if i < len(values):
                text = values[i]
                f = font(34)
                if draw.textlength(text,font=f)>260: f=font(25)
                if draw.textlength(text,font=f)>260: raise ValueError('Comparison value too wide')
                draw.text((x+142, 480), text, anchor='mm',font=f,fill=accent if i else ink)
        wrapped(' / '.join(labels[:2]), 750, size=30, max_lines=3)
    elif kind == 'checklist':
        draw.rounded_rectangle((80, 320, 640, 790), radius=20, outline=ink, width=5)
        for i, label in enumerate((labels or values)[:4]):
            y = 365+i*95
            draw.line((110,y+15,125,y+30,150,y-5),fill=accent,width=7)
            f=font(24)
            if draw.textlength(label,font=f)>430: f=font(19)
            if draw.textlength(label,font=f)>430: raise ValueError('Checklist label too wide')
            draw.text((175,y),label,font=f,fill=ink)
    else:
        draw.rounded_rectangle((85, 335, 635, 760), radius=18 if kind=='receipt' else 38, outline=ink, width=7)
        if kind == 'card':
            draw.rounded_rectangle((120, 375, 195, 430), radius=8, outline=accent, width=5)
        y=470 if kind=='card' else 370
        for line in (values or labels or ['THE REAL COST'])[:3]:
            y=wrapped(line,y,size=45 if len(line)<18 else 30,max_lines=2)+22
        if values and labels:
            wrapped(labels[0], 785, size=28, max_lines=2)
    # Recurring character silhouette. Direction is visible above, not misreported
    # as an AI-generated image. Three poses vary between scenes.
    x,y=360,970
    draw.ellipse((x-38,y-100,x+38,y-24),outline=ink,width=6)
    draw.ellipse((x-16,y-76,x-9,y-69),fill=ink)
    draw.ellipse((x+9,y-76,x+16,y-69),fill=ink)
    draw.line((x-10,y-48,x+12,y-48),fill=ink,width=4)
    draw.line((x,y-24,x,y+80),fill=ink,width=7)
    pose=index%3
    for dx, dy, angle in ((-65, 25 if pose else -35, gesture),
                          (65, -45 if pose else 25, -gesture)):
        # Rotate fixed-length arms about the shoulders, rather than stretching.
        hand_x = x + round(dx * math.cos(angle) - dy * math.sin(angle))
        hand_y = y + 10 + round(dx * math.sin(angle) + dy * math.cos(angle))
        draw.line((x,y+10,hand_x,hand_y),fill=ink,width=7)
    draw.line((x,y+80,x-45,y+140),fill=ink,width=7)
    draw.line((x,y+80,x+45,y+140),fill=ink,width=7)
    speaker=scene.get('speaker','narrator').replace('_',' ').upper()
    draw.text((360,1130),speaker,font=font(23),fill=accent,anchor='mt')
    draw.text((660,50),f'{index+1}/{count}',font=font(22),fill=ink,anchor='rt')
    image.save(path)


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    h, rem = divmod(milliseconds, 3600000); m, rem = divmod(rem, 60000); s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'


def render_cycle(editorial, output, *, voice_python, voice_root, timeout=900, transcription_python=None):
    scenes = validate(editorial)
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0 < timeout <= 1800:
        raise ValueError('Render timeout must be positive and at most 1800 seconds')
    if os.environ.get('PUBLICATION_ENABLED','false').lower()!='false':
        raise ValueError('Publication must remain disabled')
    runtime = Path(voice_python)
    if not runtime.is_absolute() or not runtime.is_file() or not os.access(runtime,os.X_OK):
        raise ValueError('Absolute executable voice runtime required')
    if transcription_python:
        asr_runtime = Path(transcription_python)
        if not asr_runtime.is_absolute() or not asr_runtime.is_file() or not os.access(asr_runtime,os.X_OK):
            raise ValueError('Absolute executable transcription runtime required')
    output = Path(output).absolute(); output.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':1,'status':'BLOCKED','technical_status':'PENDING',
             'publication_enabled':False,'paid_generation_enabled':False,'production_approved':False,
             'full_av_review':False,'editorial_sha256':editorial_digest(editorial),
             'started_at':datetime.now(timezone.utc).isoformat(),
             'scope':'Fresh offline speech and original diagram-based picture video; technical verification only.',
             'motion':{'kind':'periodic_arm_gesture','frame_count':MOTION_FRAMES,
                       'source_fps':MOTION_FPS,'loop_seconds':MOTION_FRAMES/MOTION_FPS,
                       'output_fps':24,'scope':MOTION_SCOPE}}
    deadline=time.monotonic()+timeout
    write(output/'render.json',receipt); write(output/'editorial.json',editorial)
    try:
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PUBLICATION_ENABLED='false',
                 OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
        run([runtime,Path(__file__).resolve(),'--synthesize','--editorial',output/'editorial.json',
             '--output',output,'--voice-root',Path(voice_root).resolve()],output/'voice.log',deadline,env)
        voice=json.loads((output/'voice.json').read_text())
        clips=voice['clips']
        if len(clips)!=len(scenes): raise ValueError('Missing voice clips')
        rows=[]; captions=['WEBVTT','']; start=0; segments=[]
        for index,(scene,clip) in enumerate(zip(scenes,clips)):
            wav=output/f'voice-{index:02d}.wav'
            if clip['audio_sha256']!=digest(wav) or clip['text_sha256']!=hashlib.sha256(scene['narration'].encode()).hexdigest():
                raise ValueError('Narration binding mismatch')
            duration=math.ceil((clip['duration_seconds']+.28)*24)/24
            if start+duration>600: raise ValueError('Video exceeds ten minute limit')
            panel=output/f'panel-{index:02d}.png'; draw_panel(scene,panel,index,len(scenes))
            motion_dir=output/f'motion-{index:02d}'; motion_dir.mkdir()
            motion_hashes={}
            for frame_index in range(MOTION_FRAMES):
                if time.monotonic() >= deadline: raise TimeoutError('Cycle render deadline exceeded during motion frames')
                frame=motion_dir/f'frame-{frame_index:02d}.png'
                if frame_index == 0:
                    frame.write_bytes(panel.read_bytes())
                else:
                    draw_panel(scene,frame,index,len(scenes),phase=frame_index/MOTION_FRAMES)
                motion_hashes[frame.name]=digest(frame)
            segment=output/f'segment-{index:02d}.mp4'
            run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-threads','2',
                 '-stream_loop','-1','-framerate',str(MOTION_FPS),'-start_number','0',
                 '-i',motion_dir/'frame-%02d.png','-i',wav,'-t',f'{duration:.6f}',
                 '-vf','scale=720:1280,setsar=1,fps=24','-af','apad','-c:v','libx264','-preset','veryfast',
                 '-crf','20','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','24000','-ac','1',
                 '-movflags','+faststart',segment],output/f'encode-{index:02d}.log',deadline)
            # Caption groups are evenly timed within the measured clip. They are
            # explicitly approximate until independent ASR alignment is supplied.
            words=scene['narration'].split();groups=[words[i:i+7] for i in range(0,len(words),7)]
            for i,group in enumerate(groups):
                a=start+clip['duration_seconds']*i/len(groups);b=start+clip['duration_seconds']*(i+1)/len(groups)
                captions.extend([f'{timestamp(a)} --> {timestamp(b)}',html.escape(' '.join(group)),''])
            rows.append({'scene_id':scene['id'],'start':start,'end':start+duration,
                         'narration_end':start+clip['duration_seconds'],'panel':panel.name,
                         'panel_sha256':digest(panel),'voice_sha256':digest(wav),'segment_sha256':digest(segment),
                         'motion_directory':motion_dir.name,'motion_frames_sha256':motion_hashes})
            segments.append(segment.name);start+=duration
        (output/'segments.txt').write_text(''.join("file '"+name+"'\n" for name in segments))
        run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-f','concat','-safe','1',
             '-i',output/'segments.txt','-c','copy','-movflags','+faststart',output/'video.mp4'],output/'concat.log',deadline)
        (output/'captions.vtt').write_text('\n'.join(captions)+'\n')
        run(['ffmpeg','-nostdin','-v','error','-i',output/'video.mp4','-f','null','-'],output/'decode.log',deadline)
        run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',output/'video.mp4'],output/'probe.json',deadline)
        probe=json.loads((output/'probe.json').read_text());streams=probe['streams']
        video=next(s for s in streams if s['codec_type']=='video');audio=next(s for s in streams if s['codec_type']=='audio')
        if (video['width'],video['height'],video['codec_name'],audio['codec_name'])!=(720,1280,'h264','aac'):
            raise ValueError('Output media contract mismatch')
        if abs(float(probe['format']['duration'])-start)>.25:
            raise ValueError('Output duration differs from scene timeline')
        write(output/'timeline.json',{'scenes':rows,'duration_seconds':start,'publication_enabled':False})
        asr=None
        if transcription_python:
            asr_env=dict(env,HF_HOME=os.environ.get('CYZOR_ASR_HF_HOME',str(Path.home()/'.cache/huggingface')))
            run([transcription_python,Path(__file__).resolve(),'--transcribe','--editorial',output/'editorial.json',
                 '--output',output,'--voice-root',Path(voice_root).resolve()],output/'transcription.log',deadline,asr_env)
            asr=json.loads((output/'transcription.json').read_text())
            if (asr.get('status')!='PASS' or asr.get('candidate_sha256')!=digest(output/'video.mp4')
                    or asr.get('editorial_sha256')!=editorial_digest(editorial)
                    or asr.get('caption_sha256')!=digest(output/'captions.vtt')):
                raise ValueError('Encoded transcription receipt identity mismatch')
        receipt.update(status='AWAITING_REVIEW',technical_status='PASS',candidate_sha256=digest(output/'video.mp4'),
                       caption_sha256=digest(output/'captions.vtt'),voice_receipt_sha256=digest(output/'voice.json'),
                       timeline_sha256=digest(output/'timeline.json'),duration_seconds=float(probe['format']['duration']),
                       scenes=rows,caption_timing='observed_word_timestamps' if asr else 'approximate_groups_over_measured_speech',
                       independent_transcription_verified=bool(asr),voice_model=voice['model_revision'])
        if asr: receipt['transcription_receipt_sha256']=digest(output/'transcription.json')
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired,TimeoutError) as error:
        receipt.update(status='BLOCKED',technical_status='FAIL',reason=str(error))
    finally:
        receipt['finished_at']=datetime.now(timezone.utc).isoformat();write(output/'render.json',receipt)
    return receipt


def compare_transcription(expected, actual, normalize):
    """Strict ordered comparison plus exact numeric/negation tokens.

    Expected narration is consumed only after independent recognition; never
    used as a recognizer prompt. Ordered critical tokens reject swapped numbers,
    but this lexical check does not certify semantic equivalence or naturalness.
    """
    expected_words, actual_words = normalize(expected).split(), normalize(actual).split()
    ratio = difflib.SequenceMatcher(None, expected_words, actual_words, autojunk=False).ratio()
    ec, ac = Counter(expected_words), Counter(actual_words)
    recall = sum(min(v, ac[k]) for k, v in ec.items()) / max(1, len(expected_words))
    critical = set(('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion trillion dollar cent percent minus plus point not never no cannot without').split())
    def critical_sequence(words):
        return [word for word in words if word in critical or any(character.isdigit() for character in word)]
    critical_match = critical_sequence(expected_words) == critical_sequence(actual_words)
    return {'ordered_word_similarity': ratio, 'word_recall': recall,
            'critical_numeric_and_negation_tokens_match': critical_match,
            'passed': bool(expected_words) and ratio >= .96 and recall >= .96 and critical_match}


def _caption_sentence_end(text):
    """Conservative English ASR punctuation heuristic, not a sentence parser."""
    token = text.strip().rstrip('"\'’”)]}')
    if token.endswith(('!', '?')):
        return True
    if not token.endswith('.'):
        return False
    if token.lower() in {'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.',
                         'st.', 'vs.', 'etc.', 'e.g.', 'i.e.', 'no.', 'fig.',
                         'approx.', 'inc.', 'ltd.'}:
        return False
    # Initials and dotted acronyms (A., U.S.) are ambiguous; do not force a split.
    parts = token[:-1].split('.')
    return not all(len(part) == 1 and part.isalpha() for part in parts)


def observed_captions(words, duration):
    """Group observed words at punctuation/0.5s pauses, with a seven-word cap.

    This heuristic preserves recognized text and timestamps. It does not prove
    sentence or scene alignment, readability, or listening acceptance.
    """
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Finite positive encoded media duration required')
    if not isinstance(words,list) or not words:
        raise ValueError('Observed ASR word timestamps required')
    previous=0.0
    for word in words:
        start,end=word['start'],word['end']
        if (type(start) not in (int,float) or type(end) not in (int,float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start <= end <= duration or start < previous-.02
                or not isinstance(word['word'],str) or not word['word'].strip()):
            raise ValueError('Invalid observed word timing')
        previous=end
    groups=[]; group=[]
    for word in words:
        # Zero-duration tokens may join a positive cue; never invent a duration.
        if group and group[-1]['end'] > group[0]['start'] and (
                _caption_sentence_end(group[-1]['word'])
                or word['start'] - group[-1]['end'] >= .5):
            groups.append(group); group=[]
        group.append(word)
        if len(group) == 7:
            groups.append(group); group=[]
    if group: groups.append(group)
    lines=['WEBVTT','']
    for group in groups:
        start,end=group[0]['start'],group[-1]['end']
        if end<=start:raise ValueError('Empty observed caption duration')
        text=' '.join(' '.join(w['word'].split()) for w in group)
        lines.extend([f'{timestamp(start)} --> {timestamp(end)}',html.escape(text),''])
    return '\n'.join(lines)+'\n'


def pinned_asr_snapshot():
    """Verify the recorded immutable ASR assets before model deserialization.

    Normal Hugging Face snapshot links into this cache's blobs are supported.
    Missing assets never trigger a download, and mutable refs/main is ignored.
    """
    hub = Path(os.environ.get('HF_HUB_CACHE', str(Path(os.environ.get(
        'HF_HOME', str(Path.home() / '.cache/huggingface'))) / 'hub'))).resolve()
    snapshot = hub / 'models--Systran--faster-whisper-base.en' / 'snapshots' / ASR_REVISION
    if not snapshot.is_dir() or not snapshot.resolve().is_relative_to(hub):
        raise ValueError('Pinned ASR snapshot unavailable inside selected cache')
    if {path.name for path in snapshot.iterdir()} != set(ASR_ASSETS):
        raise ValueError('Pinned ASR snapshot must contain exactly the verified assets')
    for name, (size, expected) in ASR_ASSETS.items():
        path = snapshot / name
        if not path.is_file() or not path.resolve().is_relative_to(hub):
            raise ValueError('Pinned ASR asset outside selected cache: ' + name)
        if path.stat().st_size != size or digest(path) != expected:
            raise ValueError('Pinned ASR asset size/hash mismatch: ' + name)
    return snapshot, {'repository': ASR_REPOSITORY, 'revision': ASR_REVISION,
                      'files': {name: {'size_bytes': size, 'sha256': sha}
                                for name, (size, sha) in ASR_ASSETS.items()}}


def encoded_media_duration(video):
    """Read the playable container bound, not padded ASR decode length."""
    result = subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'json', str(video)], timeout=20)
    duration = float(json.loads(result)['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Finite positive encoded media duration required')
    return duration


def transcribe_encoded(editorial, output, voice_root):
    """Independent offline recognizer reads the encoded MP4 audio stream."""
    snapshot, model_identity = pinned_asr_snapshot()
    from faster_whisper import WhisperModel
    def no_network(*args,**kwargs):raise RuntimeError('Network disabled during ASR')
    socket.socket.connect=no_network
    helper=Path(voice_root).resolve()/'scripts/free_transcription_qa.py'
    spec=importlib.util.spec_from_file_location('cyzor_transcription_helpers',helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    video=output/'video.mp4'; candidate_hash=digest(video)
    media_duration=encoded_media_duration(video)
    samples,duration=module.decode_transcription_audio(video)
    model=WhisperModel(str(snapshot),device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)
    segments,info=model.transcribe(samples,language='en',beam_size=5,word_timestamps=True,
        vad_filter=True,condition_on_previous_text=True,
        suppress_tokens=module.spoken_number_suppression(model.hf_tokenizer))
    words=[]; texts=[]
    for segment in segments:
        texts.append(segment.text.strip())
        for word in segment.words or []:
            words.append({'word':word.word.strip(),'start':float(word.start),'end':float(word.end),
                          'probability':float(word.probability)})
    actual=' '.join(texts); expected=' '.join(scene['narration'] for scene in editorial['scenes'])
    comparison=compare_transcription(expected,actual,module.norm)
    if pinned_asr_snapshot()[1] != model_identity:
        raise ValueError('Pinned ASR identity changed during recognition')
    report={'schema_version':1,'status':'FAIL','engine':'faster-whisper','model':'base.en',
            'model_identity':model_identity,
            'candidate_sha256':candidate_hash,'editorial_sha256':editorial_digest(editorial),
            'expected_text':expected,'actual_transcript':actual,'words':words,'comparison':comparison,
            'duration_seconds':duration,'encoded_media_duration_seconds':media_duration,'helper_sha256':digest(helper),'publication_enabled':False,
            'production_approved':False,'full_av_review':False,
            'scope':'Encoded speech recognition and observed word timing; not semantic equivalence, factual, creative or listening approval.'}
    if comparison['passed']:
        captions=observed_captions(words,media_duration)
        if digest(video)!=candidate_hash:raise ValueError('Candidate changed during ASR')
        (output/'captions.vtt').write_text(captions)
        report.update(status='PASS',caption_sha256=digest(output/'captions.vtt'))
    write(output/'transcription.json',report)
    if report['status']!='PASS':raise ValueError('Independent encoded speech comparison failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--synthesize',action='store_true');mode.add_argument('--transcribe',action='store_true')
    parser.add_argument('--editorial',required=True);parser.add_argument('--output',required=True);parser.add_argument('--voice-root',required=True)
    args=parser.parse_args();function=synthesize if args.synthesize else transcribe_encoded
    function(json.loads(Path(args.editorial).read_text()),Path(args.output),args.voice_root)
