"""Boundary tests plus optional actual pinned CLI run; no website/model calls."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'integrations'))
from obscura import adapter, runtime
import run as worker
import hosted_job


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.job={'tool':'obscura','operation':'inspect-local-web-page',
            'input':str(ROOT/'integrations/jobs/obscura-fixture/index.html'),
            'output':str(self.directory/'result.json'),'publication_enabled':False,'paid_generation_enabled':False}

    def test_exact_reviewed_job_and_no_raw_navigation_or_code(self):
        adapter.validate(self.job)
        for change in ({'url':'https://example.com'},{'args':['--stealth']},{'eval':'document.cookie'},
                       {'runtime':'/elsewhere'},{'publication_enabled':True},{'paid_generation_enabled':0},
                       {'operation':'scrape'}):
            with self.subTest(change=change),self.assertRaises(ValueError),patch.object(adapter,'verify_runtime') as launch:
                adapter.dispatch(dict(self.job,**change),self.directory)
                launch.assert_not_called()
        missing=dict(self.job);missing.pop('publication_enabled')
        with self.assertRaises(ValueError):adapter.validate(missing)

    def test_changed_or_linked_fixture_rejected_before_browser(self):
        modified=self.directory/'page.html';modified.write_text('<script>fetch("http://127.0.0.1")</script>')
        with self.assertRaises(ValueError):adapter.validate(dict(self.job,input=str(modified)))
        modified.unlink();modified.symlink_to(self.job['input'])
        with self.assertRaises(ValueError):adapter.validate(dict(self.job,input=str(modified)))

    def test_release_manifest_is_exact_and_does_not_require_vendor_git(self):
        self.assertEqual(worker.source('obscura'),ROOT/'integrations/obscura')
        (self.directory/'release-pin.json').write_text(json.dumps(dict(runtime.PIN,version='latest')))
        with self.assertRaises(ValueError):runtime.verify_source_manifest(self.directory)

    def test_unverified_binary_and_existing_install_are_not_overwritten(self):
        (self.directory/'obscura').write_text('fake');(self.directory/'obscura-worker').write_text('fake')
        with self.assertRaises(ValueError):runtime.verify_runtime(self.directory)
        with self.assertRaises(ValueError):runtime.install(self.directory)
        self.assertEqual((self.directory/'obscura').read_text(),'fake')

    def test_bad_archive_creates_no_runtime(self):
        archive=self.directory/'bad.tar.gz';archive.write_bytes(b'invalid')
        target=self.directory/'runtime'
        with self.assertRaises(ValueError):runtime.install(target,archive)
        self.assertFalse(target.exists())

    def test_environment_drops_provider_proxy_loader_and_browser_hooks(self):
        with patch.dict(os.environ,OPENAI_API_KEY='fixture',HTTPS_PROXY='fixture',LD_PRELOAD='fixture',
                        OBSCURA_ALLOW_PRIVATE_NETWORK='1',OBSCURA_STEALTH='1'):
            env=adapter.clean_environment(self.directory)
        for key in ('OPENAI_API_KEY','HTTPS_PROXY','LD_PRELOAD','OBSCURA_ALLOW_PRIVATE_NETWORK','OBSCURA_STEALTH'):
            self.assertNotIn(key,env)
        self.assertNotIn('HOME',env);self.assertEqual(env['PAID_GENERATION_ENABLED'],'false')

    def test_hosted_dispatch_registers_direct_owned_job(self):
        job=hosted_job.load_job('obscura-local-page.job.json',self.directory)
        self.assertIn('obscura',hosted_job.DIRECT_TOOLS)
        self.assertEqual(job,self.job)
        with patch('obscura.adapter.dispatch',return_value={'status':'BLOCKED','publication_enabled':False}) as dispatch:
            result=worker.run(job,self.directory/'runtime')
        self.assertEqual(result['status'],'BLOCKED');dispatch.assert_called_once()
        self.assertFalse(Path(str(self.job['output'])+'.receipt.json').exists())

    def test_output_alias_and_dangling_receipt_link_rejected(self):
        with self.assertRaises(ValueError):adapter.validate(dict(self.job,output=str(self.directory/'result.png')))
        Path(str(self.job['output'])+'.receipt.json').symlink_to(self.directory/'nonexistent')
        with patch.object(adapter,'verify_runtime',return_value=Path('/unused')),self.assertRaises(ValueError):
            adapter.dispatch(self.job,self.directory)

    def test_public_urls_reject_private_credentials_and_unknown_hosts(self):
        adapter.public_url('https://example.com/')
        for url in ('http://example.com','https://localhost','https://127.0.0.1','https://10.0.0.1',
                    'https://example.com@127.0.0.1','https://user:pass@example.com','https://example.com:443',
                    'https://example.com/?token=secret','https://unreviewed.example','file:///etc/passwd'):
            with self.subTest(url=url),self.assertRaises(ValueError):adapter.public_url(url)

    def test_corrupt_png_is_not_evidence(self):
        png=self.directory/'fake.png';png.write_bytes(b'\x89PNG\r\n\x1a\n'+b'wrong'*50)
        with self.assertRaises(ValueError):adapter.png_metadata(png)

    @unittest.skipUnless(os.environ.get('OBSCURA_RUNTIME'),'Set explicit installed runtime for actual CLI proof')
    def test_actual_pinned_cli_dom_and_png_and_no_overwrite(self):
        actual=Path(os.environ['OBSCURA_RUNTIME'])
        result=adapter.dispatch(self.job,actual)
        self.assertEqual(result['observed']['after'],'Review ready')
        self.assertEqual(result['screenshot']['width'],1280)
        self.assertTrue(result['screenshot']['png_verified'])
        self.assertFalse(result['production_ready'])
        with self.assertRaises(ValueError):adapter.dispatch(self.job,actual)


if __name__=='__main__':unittest.main()
