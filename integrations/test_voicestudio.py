import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from hosted_job import load_job
from voicestudio.validation import validate_audio


class VoiceStudioTests(unittest.TestCase):
    def test_reviewed_voice_job_owns_output_path(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'out'
            job=load_job('voicestudio-narration.job.json', output)
            self.assertEqual(Path(job['output']),output/'result.wav')
            self.assertFalse(job['publication_enabled'])

    def test_silence_wrong_rate_and_clipping_do_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audio.wav'
            for rate, samples, valid in [(24000,[0]*24000,False),(16000,[1000]*16000,False),
                (24000,[32767]*24000,False),(24000,[int(3000*math.sin(n/10)) for n in range(24000)],True)]:
                with wave.open(str(path),'wb') as audio:
                    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate)
                    audio.writeframes(struct.pack('<'+'h'*len(samples),*samples))
                if valid:
                    self.assertEqual(validate_audio(path)['duration_seconds'],1)
                else:
                    with self.assertRaises(ValueError):validate_audio(path)

    def test_unreviewed_directory_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);jobs=root/'integrations/jobs';jobs.mkdir(parents=True)
            (jobs/'source').mkdir()
            (jobs/'voice.job.json').write_text(json.dumps({'tool':'voicestudio','operation':'synthesize','input':'source',
                'publication_enabled':False,'paid_generation_enabled':False}))
            with self.assertRaises(ValueError):load_job('voice.job.json',root/'out',root)


if __name__=='__main__':unittest.main()
