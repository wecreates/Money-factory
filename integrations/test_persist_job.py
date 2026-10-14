import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from persist_job import persist


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'repo'
        self.artifact=Path(self.temp.name)/'artifact'
        self.root.mkdir();self.artifact.mkdir()
        (self.root/'integrations/jobs').mkdir(parents=True)
        self.job={'tool':'youtube-automation-agent','operation':'audit','publication_enabled':False,'paid_generation_enabled':False}
        (self.root/'integrations/jobs/audit.job.json').write_text(json.dumps(self.job))
        (self.root/'integrations/repositories.json').write_text(json.dumps({'repositories':[{'id':self.job['tool'],'revision':'a'*40}]}))
        for command in (['git','init','-q'],['git','add','.'],['git','-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','fixture']):
            subprocess.run(command,cwd=self.root,check=True)
        self.revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip()
        self.data=b'{"status":"attention_required"}\n'
        self.receipt={'tool':self.job['tool'],'operation':'audit','revision':'a'*40,'status':'PASS','publication_enabled':False,'output_sha256':hashlib.sha256(self.data).hexdigest()}
        self.evidence={'schema_version':1,'job':'audit.job.json','job_sha256':hashlib.sha256(json.dumps(self.job).encode()).hexdigest(),
            'repository_revision':self.revision,'content_control_revision':'b'*40,'publication_enabled':False,'paid_generation_enabled':False,'output':'result.json'}
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        (self.artifact/'result.json').write_bytes(self.data)
        (self.artifact/'result.json.receipt.json').write_text(json.dumps(self.receipt))
        (self.artifact/'job-evidence.json').write_text(json.dumps(self.evidence))

    def run_persist(self):
        return persist(self.artifact,'123','1',self.revision,self.root)

    def test_persist_reload_and_idempotent_replay(self):
        destination=self.run_persist()
        self.assertEqual((destination/'result.json').read_bytes(),self.data)
        record=json.loads((destination/'record.json').read_text())
        self.assertTrue(record['result_persisted'])
        self.assertFalse(record['production_ready'])
        self.assertEqual(self.run_persist(),destination)
        # An operation pass must not erase an audit's adverse findings.
        self.assertEqual(json.loads((destination/'result.json').read_text())['status'],'attention_required')

    def test_tampering_never_persists(self):
        for field,value,target in [('output_sha256','c'*64,self.receipt),('revision','c'*40,self.receipt),
                ('job_sha256','c'*64,self.evidence),('publication_enabled',True,self.evidence),
                ('job','../audit.job.json',self.evidence),('output','result.mp4',self.evidence)]:
            old=target[field];target[field]=value;self.write()
            with self.subTest(field=field),self.assertRaises(ValueError):self.run_persist()
            self.assertFalse((self.root/'integrations/results').exists())
            target[field]=old
        self.write()
        (self.artifact/'result.json').write_text('{"tampered":true}')
        with self.assertRaises(ValueError):self.run_persist()

    def test_rea_engineering_receipt_uses_money_factory_identity(self):
        self.job.update(tool='rea', operation='mcp-smoke')
        (self.root/'integrations/jobs/audit.job.json').write_text(json.dumps(self.job))
        (self.root/'integrations/repositories.json').write_text(json.dumps({
            'repositories':[], 'engineering_tools':[{'id':'rea','revision':'npm:rea-agents@6.4.0'}]}))
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','rea fixture'],cwd=self.root,check=True)
        self.revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip()
        self.receipt.update(tool='rea',operation='mcp-smoke',revision='npm:rea-agents@6.4.0')
        self.evidence.update(repository_revision=self.revision,execution_engine='money-factory',
            content_control_revision=None,job_sha256=hashlib.sha256(json.dumps(self.job).encode()).hexdigest())
        self.write()
        self.assertTrue((self.run_persist()/'result.json').exists())
        self.evidence['execution_engine']='content-control';self.write()
        with self.assertRaisesRegex(ValueError,'Money Factory'):self.run_persist()

    def test_conflicting_replay_rejected(self):
        target=self.run_persist()
        (target/'record.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'immutable'):self.run_persist()

    def test_symlink_input_rejected(self):
        (self.artifact/'result.json').unlink()
        (self.artifact/'result.json').symlink_to(self.root/'integrations/jobs/audit.job.json')
        with self.assertRaises(ValueError):self.run_persist()


if __name__=='__main__':unittest.main()
