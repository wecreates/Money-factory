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

    def prepare_voice_fixture(self):
        import math, struct, wave
        from voicestudio.setup_runtime import REVISION, MODEL, MODEL_REVISION
        self.job.update(tool='voicestudio', operation='synthesize', input='voice.input.json')
        request={'text':'Reviewed narration.','publication_enabled':False,'paid_generation_enabled':False}
        (self.root/'integrations/jobs/voice.input.json').write_text(json.dumps(request))
        (self.root/'integrations/jobs/audit.job.json').write_text(json.dumps(self.job))
        (self.root/'integrations/repositories.json').write_text(json.dumps({'repositories':[],
            'media_tools':[{'id':'voicestudio','revision':REVISION}]}))
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','voice fixture'],cwd=self.root,check=True)
        self.revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip()
        audio=self.artifact/'result.wav'
        with wave.open(str(audio),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
            wav.writeframes(struct.pack('<'+'h'*24000,*[int(3000*math.sin(n/10)) for n in range(24000)]))
        digest=hashlib.sha256(audio.read_bytes()).hexdigest()
        self.receipt.update(tool='voicestudio',operation='synthesize',revision=REVISION,output_sha256=digest)
        self.evidence.update(repository_revision=self.revision,execution_engine='money-factory',
            content_control_revision=None,job_sha256=hashlib.sha256(json.dumps(self.job).encode()).hexdigest(),output='result.wav')
        (self.artifact/'result.wav.receipt.json').write_text(json.dumps(self.receipt))
        self.voice_metadata={'schema_version':1,'status':'PASS','tool':'voicestudio','operation':'synthesize',
            'engine':'kittentts','upstream_revision':REVISION,'model':MODEL,'model_revision':MODEL_REVISION,
            'text_sha256':hashlib.sha256(request['text'].encode()).hexdigest(),'voice':'expr-voice-2-f',
            'speed':1.0,'language':'en','synthetic':True,'output_sha256':digest,
            'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False}
        (self.artifact/'result.wav.generation.json').write_text(json.dumps(self.voice_metadata))
        (self.artifact/'job-evidence.json').write_text(json.dumps(self.evidence))
        return audio

    def test_voice_media_is_verified_but_only_provenance_is_committed(self):
        audio=self.prepare_voice_fixture()
        result=self.run_persist()
        self.assertTrue((result/'result.wav.generation.json').exists())
        self.assertFalse((result/'result.wav').exists())
        audio.write_bytes(b'corrupt')
        with self.assertRaises(Exception):self.run_persist()

    def test_voice_provenance_tampering_is_rejected_before_persistence(self):
        self.prepare_voice_fixture()
        for field,value in [('upstream_revision','b'*40),('model','wrong/model'),('model_revision','b'*40),
                ('text_sha256','c'*64),('voice','expr-voice-3-m'),('speed',1.5),('language','fr'),
                ('status','FAIL'),('tool','rea'),('operation','clone'),('synthetic',False),
                ('publication_enabled',True),('paid_generation_enabled',True),('production_ready',True)]:
            altered=self.voice_metadata | {field:value}
            (self.artifact/'result.wav.generation.json').write_text(json.dumps(altered))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'provenance'):
                self.run_persist()
            self.assertFalse((self.root/'integrations/results').exists())

    def prepare_obscura_fixture(self):
        # Synthetic valid PNG and a real temporary Git history; no browser claim.
        import struct,zlib
        from obscura.runtime import PIN
        from obscura.adapter import png_metadata
        self.job.update(tool='obscura',operation='inspect-public-page',input='public.json')
        request=b'{"url":"https://example.com/"}'
        (self.root/'integrations/jobs/public.json').write_bytes(request)
        (self.root/'integrations/jobs/audit.job.json').write_text(json.dumps(self.job))
        (self.root/'integrations/obscura').mkdir()
        (self.root/'integrations/obscura/release-pin.json').write_text(json.dumps(PIN))
        (self.root/'integrations/repositories.json').write_text(json.dumps({'repositories':[],
            'engineering_tools':[{'id':'obscura','revision':PIN['revision']}]}))
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','obscura fixture'],cwd=self.root,check=True)
        self.revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip()
        def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1280,720,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(720*(1+1280*4))))+chunk(b'IEND',b'')
        (self.artifact/'result.png').write_bytes(png)
        self.obscura_result={'tool':'obscura','operation':self.job['operation'],'version':PIN['version'],'status':'PASS',
            'input_sha256':hashlib.sha256(request).hexdigest(),'upstream_revision':PIN['revision'],
            'archive_sha256':PIN['archive_sha256'],'binary_sha256':PIN['files']['obscura']['sha256'],
            'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False,
            'screenshot':dict(png_metadata(self.artifact/'result.png'),file='result.png')}
        self.receipt.update(tool='obscura',operation=self.job['operation'],revision=PIN['revision'])
        self.evidence.update(repository_revision=self.revision,execution_engine='money-factory',content_control_revision=None,
            job_sha256=hashlib.sha256(json.dumps(self.job).encode()).hexdigest())
        self.write_obscura()

    def write_obscura(self):
        self.data=json.dumps(self.obscura_result).encode()
        self.receipt['output_sha256']=hashlib.sha256(self.data).hexdigest()
        self.write()

    def test_obscura_direct_evidence_accepts_bound_png_without_committing_it(self):
        self.prepare_obscura_fixture()
        destination=self.run_persist()
        self.assertTrue((destination/'result.json').exists())
        self.assertFalse((destination/'result.png').exists())
        (self.artifact/'result.png').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.run_persist()

    def test_obscura_inner_identity_tampering_is_rejected(self):
        self.prepare_obscura_fixture()
        for field,value in [('input_sha256','0'*64),('archive_sha256','0'*64),('binary_sha256','0'*64),
                            ('tool','rea'),('operation','scrape'),('version','latest'),('production_ready',True)]:
            old=self.obscura_result[field];self.obscura_result[field]=value;self.write_obscura()
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Obscura'):
                self.run_persist()
            self.assertFalse((self.root/'integrations/results').exists())
            self.obscura_result[field]=old
        self.obscura_result['screenshot']['sha256']='0'*64;self.write_obscura()
        with self.assertRaisesRegex(ValueError,'screenshot'):self.run_persist()

    def test_conflicting_replay_rejected(self):
        target=self.run_persist()
        (target/'record.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'immutable'):self.run_persist()

    def test_symlink_input_rejected(self):
        (self.artifact/'result.json').unlink()
        (self.artifact/'result.json').symlink_to(self.root/'integrations/jobs/audit.job.json')
        with self.assertRaises(ValueError):self.run_persist()


if __name__=='__main__':unittest.main()
