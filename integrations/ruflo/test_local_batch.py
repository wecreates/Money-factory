from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('local_batch', Path(__file__).with_name('local_batch.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.batch = dict(publication_enabled=False, endpoint='http://127.0.0.1:11434',
            workers=2,max_tokens=64,timeout_seconds=30,worker_memory_mb=256,
            shared_model_memory_mb=1024,render_memory_mb=2048,render_cpu=2,model='qwen3:1.7b',tasks=[{'id':'writer','prompt':'Draft a hook.'}])
    def test_remote_endpoints_and_redirect_targets_are_not_accepted(self):
        for endpoint in ['https://ollama.com','http://localhost:11434','http://127.0.0.1:11434/path',
                         'http://user@127.0.0.1:11434','http://127.0.0.1:11434?key=secret','http://100.64.0.1:11434']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                m.validate({**self.batch,'endpoint':endpoint})
    def test_refuses_oversubscription_and_publication(self):
        for changes in [{'workers':100},{'workers':True},{'max_tokens':100000},
                        {'publication_enabled':True},{'timeout_seconds':0},{'worker_memory_mb':0}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):m.validate({**self.batch,**changes})
    def test_duplicate_task_is_rejected(self):
        with self.assertRaises(ValueError):m.validate({**self.batch,'tasks':self.batch['tasks']*2})
    def test_environment_does_not_inherit_credentials_or_loaders(self):
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'secret','NODE_OPTIONS':'--require evil','HTTP_PROXY':'http://proxy'}):
            env=m.child_environment(Path('/tmp/isolated'))
        self.assertNotIn('ANTHROPIC_API_KEY',env);self.assertNotIn('NODE_OPTIONS',env);self.assertNotIn('HTTP_PROXY',env)
    def test_capacity_block_prevents_all_execution(self):
        module=types.SimpleNamespace(collect_snapshot=lambda: {},recommend_capacity=lambda *a,**k:{'admitted_workers':0})
        with patch.dict(sys.modules,{'agent_capacity':module}), patch.object(m,'execute_task') as execute:
            result=m.admitted_batch(self.batch,'/does-not-exist')
        self.assertEqual(result['status'],'BLOCKED');execute.assert_not_called()
    def test_model_and_video_render_reserves_are_forwarded(self):
        from unittest.mock import Mock
        recommend=Mock(return_value={'admitted_workers':0})
        module=types.SimpleNamespace(collect_snapshot=lambda: {},recommend_capacity=recommend)
        with patch.dict(sys.modules,{'agent_capacity':module}):m.admitted_batch(self.batch,'unused')
        self.assertEqual(recommend.call_args.kwargs['render_memory_mb'],2048)
        self.assertEqual(recommend.call_args.kwargs['render_cpu'],2)
        self.assertEqual(recommend.call_args.kwargs['shared_model_memory_mb'],1024)

    def test_registration_or_empty_output_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as t:
            node=Path(t)/'fake';node.write_text('#!/bin/sh\nprintf "registered\\n"\n');node.chmod(0o755)
            r=m.execute_task(self.batch['tasks'][0],self.batch,Path(t),str(node))
        self.assertEqual(r['status'],'FAIL')
    def test_shared_host_lock_blocks_execution(self):
        class Busy(Exception):pass
        @contextmanager
        def locked():
            raise Busy()
            yield
        module=types.SimpleNamespace(shared_admission_lock=locked, AdmissionBusy=Busy)
        with patch.dict(sys.modules,{'agent_capacity':module}), patch.object(m,'admitted_batch') as execute:
            result=m.run_batch(self.batch,'/different-runtime')
        self.assertEqual(result['status'],'BLOCKED');execute.assert_not_called()

    def test_shared_host_lock_is_held_through_batch(self):
        state=[]
        @contextmanager
        def locked():
            state.append('held')
            try:yield
            finally:state.clear()
        module=types.SimpleNamespace(shared_admission_lock=locked, AdmissionBusy=RuntimeError)
        def execute(*args):
            self.assertEqual(state,['held'])
            return {'status':'PASS'}
        with patch.dict(sys.modules,{'agent_capacity':module}), patch.object(m,'admitted_batch',side_effect=execute):
            result=m.run_batch(self.batch,'/different-runtime')
        self.assertEqual(result['status'],'PASS');self.assertEqual(state,[])

    def test_cloud_model_ids_are_rejected(self):
        with self.assertRaises(ValueError):m.validate({**self.batch,'model':'qwen-cloud'})

    def test_remote_model_metadata_is_rejected(self):
        import io,json
        for metadata in [{'model_info':{}},{'model_info':{'size':123},'remote_host':'ollama.com'},
                         {'model_info':{'size':123},'details':{'remote_model':'remote'}}]:
            opener=types.SimpleNamespace(open=lambda *a,**k:io.BytesIO(json.dumps(metadata).encode()))
            with patch.object(m,'build_opener',return_value=opener),self.assertRaises(ValueError):
                m.verify_local_model(self.batch)

    def test_installed_local_model_metadata_is_accepted(self):
        import io,json
        opener=types.SimpleNamespace(open=lambda *a,**k:io.BytesIO(json.dumps({'model_info':{'size':123}}).encode()))
        with patch.object(m,'build_opener',return_value=opener):
            self.assertTrue(m.verify_local_model(self.batch)['model_info'])

    def test_unbounded_child_output_is_killed(self):
        with tempfile.TemporaryDirectory() as t:
            node=Path(t)/'fake';node.write_text('#!/bin/sh\nexec yes noisy\n');node.chmod(0o755)
            r=m.execute_task(self.batch['tasks'][0],self.batch,Path(t),str(node))
        self.assertEqual(r['status'],'FAIL')

    def test_nonzero_child_returns_failure(self):
        with tempfile.TemporaryDirectory() as t:
            node=Path(t)/'fake';node.write_text('#!/bin/sh\nexit 2\n');node.chmod(0o755)
            r=m.execute_task(self.batch['tasks'][0],self.batch,Path(t),str(node))
        self.assertEqual(r['status'],'FAIL')

if __name__=='__main__':unittest.main()
