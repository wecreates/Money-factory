import json
from contextlib import nullcontext
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openclaw import worker
import agent_capacity


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('shared_admission_lock', nullcontext()), ('recommend_capacity', {'admitted_workers':1})]:
            patcher=patch.object(agent_capacity,name,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(worker,'check_local_model');patcher.start();self.addCleanup(patcher.stop)
        self.job = dict(tool='openclaw', operation='run-text', publication_enabled=False,
                        paid_generation_enabled=False, output=str(self.root/'result.json'),
                        model='qwen2.5:3b', model_url='http://127.0.0.1:11434', prompt='Draft a short storyboard.',worker_memory_mb=512,shared_model_memory_mb=0,render_memory_mb=1024,render_cpu=1)

    def test_explicit_safety_flags(self):
        for field in ('publication_enabled','paid_generation_enabled'):
            for value in (None, True, 'false', 0):
                with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                    worker.validate(dict(self.job, **{field:value}))

    def test_rejects_remote_ambiguous_and_credential_urls(self):
        for url in ('http://localhost:11434','https://127.0.0.1:443','http://example.com:80',
                    'http://127.0.0.1:80/v1','http://u:p@127.0.0.1:80','http://127.0.0.1:80?x=y',
                    'http://127.0.0.1:80#x', 'http://127.0.0.1', None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                worker.validate(dict(self.job,model_url=url))

    def test_rejects_cloud_model_and_forwarded_cli_options(self):
        for model in ('qwen:cloud','https://foo','', '--deliver'):
            with self.subTest(model=model), self.assertRaises(ValueError):
                worker.validate(dict(self.job,model=model))
        with self.assertRaises(ValueError):
            worker.validate(dict(self.job,deliver=True))

    def test_environment_does_not_inherit_secrets_or_runtime_hooks(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'secret','NODE_OPTIONS':'danger','HTTP_PROXY':'remote','OPENCLAW_CONFIG_PATH':'ambient'}):
            env=worker.environment(self.root)
        for key in ('OPENAI_API_KEY','NODE_OPTIONS','HTTP_PROXY'):
            self.assertNotIn(key,env)
        self.assertEqual(env['OPENCLAW_CONFIG_PATH'],str(self.root/'config.json'))

    def test_no_installed_cli_is_blocked_not_success(self):
        with patch.object(worker.shutil,'which',return_value=None):
            result=worker.dispatch(self.job,self.root/'runtime')
        self.assertEqual(result['blockers'],['OPENCLAW_NOT_INSTALLED'])
        self.assertEqual(result['verified_agents'],0)
        self.assertFalse(result['production_ready'])
        self.assertTrue(Path(self.job['output']).exists())

    def test_real_command_shape_and_isolated_config(self):
        calls=[]
        def fake(argv,cwd,env,timeout):
            calls.append(argv)
            if '--version' in argv:return worker.VERSION
            cfg=json.loads((cwd/'config.json').read_text())
            self.assertEqual(cfg['tools']['deny'],['*'])
            self.assertEqual(cfg['agents']['defaults']['model']['fallbacks'],[])
            self.assertEqual(cfg['models']['providers']['ollama']['api'],'ollama')
            self.assertNotIn('--deliver',argv)
            self.assertIn('--local',argv)
            self.assertEqual((cwd/'prompt.txt').read_text(),self.job['prompt'])
            return json.dumps(self.success())
        with patch.object(worker,'execute',side_effect=fake):
            result=worker.run_isolated(self.job,'openclaw')
        self.assertEqual(result['text'],'draft')
        self.assertEqual(len(calls),2)

    def test_unexpected_or_error_payload_never_passes(self):
        for payload in ({'result':{'payloads':[{'text':'wrong envelope'}]}},
                        {'payloads':[]},{'payloads':[{'text':'error','isError':True}]},
                        {'payloads':[{'mediaUrl':'https://example.org/file'}]}, {'payloads':[{}]}):
            with self.subTest(payload=payload), patch.object(worker,'execute',side_effect=[worker.VERSION,json.dumps(payload)]), self.assertRaises(RuntimeError):
                worker.run_isolated(self.job,'openclaw')

    def test_wrong_version_rejected(self):
        with patch.object(worker,'execute',return_value='2026.11.60'),self.assertRaisesRegex(RuntimeError,'VERSION_MISMATCH'):
            worker.run_isolated(self.job,'openclaw')

    def test_doctor_does_not_call_model(self):
        with patch.object(worker,'execute',return_value=worker.VERSION) as call:
            result=worker.run_isolated(dict(self.job,operation='doctor'),'openclaw')
        self.assertEqual(call.call_count,1)
        self.assertFalse(result['model_execution_verified'])

    def success(self):
        model=self.job['model']
        return {'payloads':[{'text':'draft'}], 'meta': {'aborted':False, 'stopReason':'stop',
            'agentMeta':{'provider':'ollama','model':model,'usage':{'input':10,'output':4},
                'terminalReceipt':{'effective':{'provider':'ollama','model':model},'successfulToolNames':[]}},
            'executionTrace':{'winnerProvider':'ollama','winnerModel':model,'fallbackUsed':False,'runner':'embedded'}}}

    def test_nonempty_text_without_inference_metadata_rejected(self):
        with patch.object(worker,'execute',side_effect=[worker.VERSION,json.dumps({'payloads':[{'text':'draft'}]})]),self.assertRaisesRegex(RuntimeError,'INFERENCE_EVIDENCE'):
            worker.run_isolated(self.job,'openclaw')

    def test_cloud_route_fallback_zero_tokens_or_tool_use_rejected(self):
        for change in ('provider','fallback','tokens','tools','abort'):
            result=self.success()
            if change=='provider':result['meta']['agentMeta']['provider']='cloud'
            if change=='fallback':result['meta']['executionTrace']['fallbackUsed']=True
            if change=='tokens':result['meta']['agentMeta']['usage']['output']=0
            if change=='tools':result['meta']['agentMeta']['terminalReceipt']['successfulToolNames']=['exec']
            if change=='abort':result['meta']['aborted']=True
            with self.subTest(change=change),patch.object(worker,'execute',side_effect=[worker.VERSION,json.dumps(result)]),self.assertRaises(RuntimeError):
                worker.run_isolated(self.job,'openclaw')

    def test_output_not_overwritten(self):
        output=Path(self.job['output']);output.write_text('keep')
        with self.assertRaises(ValueError):worker.dispatch(self.job,self.root/'runtime')
        self.assertEqual(output.read_text(),'keep')

    def test_shared_lock_contention_blocks_execution(self):
        with patch.object(agent_capacity,'shared_admission_lock',side_effect=agent_capacity.AdmissionBusy()),patch.object(worker,'run_isolated') as call:
            result=worker.dispatch(self.job,self.root/'runtime')
        self.assertEqual(result['blockers'],['OPENCLAW_SHARED_BUDGET_BUSY']);call.assert_not_called()

    def test_capacity_block_stops_before_model_call(self):
        with patch.object(worker.shutil,'which',return_value='openclaw'),patch.object(agent_capacity,'recommend_capacity',return_value={'admitted_workers':0}),patch.object(worker,'run_isolated') as call:
            result=worker.dispatch(self.job,self.root/'runtime')
        self.assertEqual(result['blockers'],['OPENCLAW_CAPACITY_BLOCKED']);call.assert_not_called()

    def test_error_details_do_not_leak_to_report(self):
        with patch.object(worker.shutil,'which',return_value='openclaw'),patch.object(worker,'run_isolated',side_effect=ValueError('secret token')):
            result=worker.dispatch(self.job,self.root/'runtime')
        self.assertEqual(result['blockers'],['OPENCLAW_EXECUTION_FAILED'])
        self.assertNotIn('secret',json.dumps(result))
        self.assertFalse((self.root/'runtime'/'local-agent.lock').exists())

    def test_subprocess_timeout_and_output_limit(self):
        env=worker.environment(self.root)
        with self.assertRaisesRegex(RuntimeError,'TIMEOUT'):
            worker.execute([sys.executable,'-c','import time;time.sleep(10)'],self.root,env,.1)
        with self.assertRaisesRegex(RuntimeError,'OUTPUT_LIMIT'):
            worker.execute([sys.executable,'-c','print("x"*1100000)'],self.root,env,5)


class ModelMetadataTests(unittest.TestCase):
    def test_local_metadata_required_and_cloud_alias_rejected(self):
        for info, allowed in [({'model_info':{'parameters':1}},True),
                              ({'model_info':{}},False),
                              ({'model_info':{'parameters':1},'details':{'remote_host':'https://cloud'}},False),
                              ({'model_info':{'parameters':1},'remote_model':'paid'},False),
                              ({'model_info':{'parameters':1},'remote_host':'https://cloud'},False)]:
            with self.subTest(info=info),patch.object(worker.http.client,'HTTPConnection') as connection:
                response=connection.return_value.getresponse.return_value
                response.status=200;response.read.return_value=json.dumps(info).encode()
                job={'model_url':'http://127.0.0.1:11434','model':'local-alias'}
                if allowed:worker.check_local_model(job)
                else:
                    with self.assertRaises(RuntimeError):worker.check_local_model(job)
                connection.return_value.close.assert_called_once()

    def test_redirect_or_oversized_metadata_rejected(self):
        for status,body in [(302,b'{}'),(200,b'x'*65537)]:
            with patch.object(worker.http.client,'HTTPConnection') as connection:
                response=connection.return_value.getresponse.return_value
                response.status=status;response.read.return_value=body
                with self.assertRaises(RuntimeError):
                    worker.check_local_model({'model_url':'http://127.0.0.1:11434','model':'model'})

if __name__=='__main__':unittest.main()
