import json
from pathlib import Path
import tempfile
import unittest
from hosted_job import load_job


class JobBoundaryTests(unittest.TestCase):
    def test_rejects_escape_spend_publication_and_worker_owned_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            jobs=root/'integrations/jobs'
            jobs.mkdir(parents=True)
            (jobs/'input.json').write_text('{}')
            base={'tool':'youtube-automation-agent','operation':'audit','input':'input.json',
                  'publication_enabled':False,'paid_generation_enabled':False}
            for change in ({'input':'/etc/passwd'}, {'input':'../../../../etc/passwd'},
                           {'publication_enabled':True}, {'paid_generation_enabled':True},
                           {'tool':'wan21','operation':'generate'}, {'output':'/tmp/overwrite'},
                           {'service_url':'http://example.com'}):
                with self.subTest(change=change):
                    (jobs/'test.job.json').write_text(json.dumps(base|change))
                    with self.assertRaises((ValueError,FileNotFoundError)):
                        load_job('test.job.json',root/'out',root)
            (jobs/'test.job.json').write_text(json.dumps(base))
            result=load_job('test.job.json',root/'out',root)
            self.assertEqual(result['input'],str(jobs/'input.json'))
            self.assertEqual(result['output'],str(root/'out/result.json'))


if __name__=='__main__':
    unittest.main()
