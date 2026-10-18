"""A valid package hash cannot make an incomplete or aliased inventory valid."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from production_test_fixtures import COMMON_FILES, BOOK_FILES, artifact_bodies

module=importlib.util.spec_from_file_location('inventory_agent',Path(__file__).with_name('production_agent.py'))
agent=importlib.util.module_from_spec(module);module.loader.exec_module(agent)


class ProductionInventoryTests(unittest.TestCase):
    def attempt(self, platform='kdp', mutate=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job=root/'job.json';font=root/'font.ttf';out=root/'out'
            job.write_text(json.dumps({'platform':platform,'publication_enabled':False,'paid_generation_enabled':False}))
            font.write_bytes(b'fixture')
            def child(argv, **kwargs):
                package=out/'package';package.mkdir(parents=True)
                files={}
                for name in artifact_bodies(platform):
                    body=('fixture '+name).encode();(package/name).write_bytes(body)
                    files[name]=hashlib.sha256(body).hexdigest()
                if mutate:mutate(package,files)
                manifest={'schema_version':1,'platform':platform,'publication_enabled':False,'files':files}
                digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                manifest['package_sha256']=digest
                (package/'manifest.json').write_text(json.dumps(manifest))
                (out/'result.json').write_text(json.dumps({'schema_version':1,'platform':platform,
                    'status':'REVIEW_REQUIRED','publication_enabled':False,'production_ready':False,
                    'paid_generation_enabled':False,'marketplace_ready':False,'package_sha256':digest,
                    'remaining_checks':['official_template','rights','editorial','independent_visual_review',
                                        'marketplace_account','platform_preview','release_approval']}))
            with patch.object(agent,'run_review_child',side_effect=child):
                try:result=agent.run(job,root,font,out)
                except (ValueError,OSError):
                    self.assertFalse((out/'money-factory-receipt.json').exists())
                    self.assertTrue((out/'package/manifest.json').is_file())
                    raise
            self.assertEqual(json.loads((out/'money-factory-receipt.json').read_text()),result)
            return result

    def test_every_required_artifact_must_be_hash_listed(self):
        for platform in ('kdp','redbubble','teepublic','zazzle','spreadshirt'):
            for name in COMMON_FILES + (BOOK_FILES if platform=='kdp' else ()):
                with self.subTest(platform=platform,name=name):
                    def omit(package,files):files.pop(name);(package/name).unlink()
                    with self.assertRaisesRegex(ValueError,'^ARTIFACT_SET_INCOMPLETE$'):
                        self.attempt(platform,omit)

    def test_complete_inventories_and_flat_extra_are_accepted(self):
        for platform in ('kdp','redbubble','teepublic','zazzle','spreadshirt'):
            with self.subTest(platform=platform):
                def extra(package,files):
                    (package/'notes.txt').write_bytes(b'notes')
                    files['notes.txt']=hashlib.sha256(b'notes').hexdigest()
                self.assertEqual(self.attempt(platform,extra)['status'],'REVIEW_REQUIRED')

    def test_nonflat_and_absolute_aliases_are_rejected(self):
        for alias in ('./print.png','sub/../print.png','../package/print.png','absolute'):
            with self.subTest(alias=alias):
                def add_alias(package,files):
                    (package/'sub').mkdir()
                    name=str(package/'print.png') if alias=='absolute' else alias
                    files[name]=files['print.png']
                with self.assertRaisesRegex(ValueError,'^ARTIFACT_NAME_INVALID$'):
                    self.attempt(mutate=add_alias)

    def test_final_symlink_is_not_resolved_before_regular_file_open(self):
        def add_link(package,files):
            (package/'copy.png').symlink_to('print.png');files['copy.png']=files['print.png']
        with self.assertRaises(OSError):self.attempt(mutate=add_link)


if __name__=='__main__':unittest.main()
