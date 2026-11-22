"""Optional pinned real-CLI transport contract; fixture is not model inference."""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openclaw.worker import run_isolated


@unittest.skipUnless(os.getenv('OPENCLAW_TEST_CLI'), 'requires explicit pinned OpenClaw CLI')
class ContractTest(unittest.TestCase):
    def test_native_ollama_transport_has_zero_tools(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path,body))
                if self.path != '/api/chat': self.send_error(404);return
                answer={'model':'fixture:latest','created_at':'2026-11-20T00:00:00Z',
                    'message':{'role':'assistant','content':'FIXTURE_ONLY'},'done':True,
                    'done_reason':'stop','prompt_eval_count':10,'eval_count':4}
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
                self.wfile.write((json.dumps(answer)+'\n').encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            result=run_isolated({'operation':'run-text','model':'fixture:latest',
                'model_url':f'http://127.0.0.1:{server.server_port}',
                'prompt':'Return the fixture marker.','timeout_seconds':60},os.environ['OPENCLAW_TEST_CLI'])
        finally:server.shutdown();server.server_close()
        self.assertEqual(result['text'],'FIXTURE_ONLY')
        self.assertTrue(requests)
        self.assertTrue(all(not body.get('tools') for _,body in requests))
        self.assertEqual(result['provider'],'ollama')
        self.assertEqual(result['usage']['output_tokens'],4)

if __name__=='__main__':unittest.main()
