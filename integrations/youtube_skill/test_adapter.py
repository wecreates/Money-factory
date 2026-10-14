import json
import os
from pathlib import Path
import tempfile
import unittest
from adapter import command,dispatch


class InputTests(unittest.TestCase):
    def test_rejects_ambiguous_retention_axis(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'percent'):
                command('retention',{'axis':'seconds'},Path(d))

    def test_rejects_nonfinite_and_unsorted_analytics(self):
        with tempfile.TemporaryDirectory() as d:
            for csv in ('x,y\n0,100\n10,nan','x,y\n10,100\n5,90'):
                with self.assertRaises(ValueError):command('retention',{'axis':'percent','duration':60,'retention_csv':csv},Path(d))
            with self.assertRaises(ValueError):command('outliers',{'collected':[{'channel':'a','title':'b','views':float('inf')}]},Path(d))

    @unittest.skipUnless(os.environ.get('YOUTUBE_SKILL_UPSTREAM'),'Actual pinned upstream required')
    def test_all_six_real_clis_preserve_negative_findings(self):
        transcript='\n\n'.join(f'{n+1}\n00:00:{n*3:02d},000 --> 00:00:{n*3+2:02d},000\nTopic number {n} explains budgeting.' for n in range(8))
        cases={
          'hook-score':{'hook':'Hello everybody'},
          'package-lint':{'title':'Amazing everything','thumb':'Amazing everything'},
          'edit-plan':{'transcript_srt':transcript},
          'chapters':{'transcript_srt':transcript},
          'retention':{'retention_csv':'timeline_percent,audience_percent\n'+'\n'.join(f'{i*10},{100-i*5}' for i in range(11)),'axis':'percent','duration':60},
          'outliers':{'collected':[{'channel':'synthetic','title':'fixture','views':100}]}}
        with tempfile.TemporaryDirectory() as d:
            for operation,payload in cases.items():
                p=Path(d)/f'{operation}.json';p.write_text(json.dumps(payload))
                report=dispatch({'operation':operation,'input':str(p),'publication_enabled':False,'paid_generation_enabled':False},os.environ['YOUTUBE_SKILL_UPSTREAM'])
                self.assertEqual(report['execution_status'],'PASS',report)
                self.assertFalse(report['production_ready'])
                if operation=='chapters':self.assertFalse(report['findings']['valid'])
                if operation=='package-lint':self.assertTrue(report['findings'][0]['issues'])
                if operation=='outliers':self.assertEqual(report['findings']['skipped_thin_channels'],[['synthetic',1]])


if __name__=='__main__':unittest.main()
