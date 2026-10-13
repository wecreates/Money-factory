#!/usr/bin/env python3
"""Run real local CPU integration operations with synthetic fixtures; no publishing."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import urlopen
from run import ROOT, run


def smoke(runtime, executor=run):
    receipts = []
    with tempfile.TemporaryDirectory(prefix='cyzor-smoke-') as folder:
        work = Path(folder)
        video = work / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '4',
                        '-c:v', 'libx264', '-g', '24', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(video)], check=True)
        (work / 'captions.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\nIntegration test\n')
        (work / 'page.html').write_text('<html><head><title>CYZOR test</title></head><body><h1>Audit fixture</h1></body></html>')
        (work / 'content.json').write_text(json.dumps({'id': 'local-test', 'platform': 'youtube',
            'title': 'Why subscriptions add up', 'transcript': 'Review the subscriptions you use.', 'brand': 'CYZOR'}))
        (work / 'transcript.json').write_text(json.dumps({'duration': 4, 'transcript': {'segments': [
            {'start': 0, 'end': 2, 'text': 'First sentence.'}, {'start': 2, 'end': 4, 'text': 'Second sentence.'}]}}))

        def check(tool, operation, input_name, output_name, **extra):
            job = dict(tool=tool, operation=operation, output=str(work / output_name), **extra)
            if input_name:
                job['input'] = str(work / input_name)
            receipt = executor(job, runtime)
            if receipt['media']:
                assert any(s['codec_type'] == 'audio' for s in receipt['media']['streams'])
            receipts.append(receipt)
            print(f'PASS {tool}/{operation}', flush=True)
            return receipt

        clip = check('youtube-clipper-skill', 'clip', 'source.mp4', 'clip.mp4', start=1, end=3)
        assert 1.9 < clip['media']['duration'] < 2.2
        check('youtube-clipper-skill', 'captions', 'source.mp4', 'captioned.mp4', subtitles=str(work / 'captions.srt'))
        # Compare decoded pixels; a remux with no visible subtitle is not a caption pass.
        def pixels(path):
            return subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '0.5', '-i', str(path),
                '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        assert pixels(video) != pixels(work / 'captioned.mp4')
        vertical = check('openshorts', 'vertical', 'source.mp4', 'vertical.mp4')
        stream = next(s for s in vertical['media']['streams'] if s['codec_type'] == 'video')
        assert (stream['width'], stream['height']) == (1080, 1920)
        check('openshorts', 'transcript-windows', 'transcript.json', 'windows.json')
        assert 'First sentence.' in json.loads((work / 'windows.json').read_text())[0]['text']
        check('claude-seo', 'parse-html', 'page.html', 'seo.json')
        assert json.loads((work / 'seo.json').read_text())['title'] == 'CYZOR test'
        check('youtube-automation-agent', 'audit', 'content.json', 'audit.json')
        assert json.loads((work / 'audit.json').read_text())['engine']['name'] == 'darkzseo'
        check('ruflo', 'remember-project', None, 'memory.txt')
        log = (work / 'toonflow.log').open('w')
        data = work / 'toonflow-data'
        env = dict(os.environ, TOONFLOW_DATA_DIR=str(data), PUBLICATION_ENABLED='false')
        server = subprocess.Popen([str(runtime / 'bun/node_modules/.bin/bun'),
            str(ROOT / 'integrations/toonflow-server.ts')], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            for _ in range(40):
                try:
                    with urlopen('http://127.0.0.1:3000/api/workspaces/list', timeout=1) as response:
                        info = json.load(response)
                    break
                except Exception:
                    if server.poll() is not None:
                        raise RuntimeError('Toonflow exited: ' + (work / 'toonflow.log').read_text())
                    time.sleep(0.25)
            else:
                raise RuntimeError('Toonflow did not become ready')
            workspace = info['data']['absolutePath']
            assert Path(workspace).resolve().is_relative_to(data.resolve())
            check('toonflow-app', 'import-brief', 'content.json', 'toonflow-result.json', workspace_directory=workspace)
            saved = json.loads((Path(workspace) / 'cyzor-content-brief.json').read_text())
            assert saved['publication_enabled'] is False and saved['id'] == 'local-test'
        finally:
            server.terminate()
            server.wait(timeout=10)
            log.close()
        # Negative tests: do not overwrite existing output or permit publishing/spend.
        invalid = [dict(tool='youtube-clipper-skill', operation='clip', input=str(video),
                    output=str(work / 'clip.mp4'), start=0, end=1),
                   dict(publication_enabled=True), dict(paid_generation_enabled=True)]
        for job in invalid:
            try:
                executor(job, runtime)
            except ValueError:
                continue
            raise AssertionError('A prohibited operation was accepted')
    return {'status': 'PASS', 'scope': 'Eight local CPU operations; Wan generation and hosted operation not verified',
            'publication_enabled': False, 'receipts': receipts, 'negative_checks': 3}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = smoke(args.runtime.resolve())
    args.report.write_text(json.dumps(report, indent=2) + '\n')
