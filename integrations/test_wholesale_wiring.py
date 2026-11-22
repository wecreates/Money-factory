import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
from unittest.mock import patch
import unittest
import run


class WholesaleWorkerTests(unittest.TestCase):
    def test_malformed_catalog_emits_blocked_reports_and_bound_receipts(self):
        authored=subprocess.run(['node','--input-type=module','-e',
            "import {fixture} from './integrations/wholesale/offer-contract.fixture.mjs'; const c=fixture(); c.catalog=null; console.log(JSON.stringify(c));"],cwd=run.ROOT,capture_output=True,text=True,check=True)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'synthetic-invalid.json'
            source.write_text(authored.stdout,encoding='utf-8')
            for operation,field,items in [('listing-draft','draft_status','drafts'),('offer-contract','contract_status','plans')]:
                output=root/(operation+'.json')
                receipt=run.run(self.job(output)|dict(operation=operation,input=str(source)),root/'runtime')
                report=json.loads(output.read_text())
                self.assertEqual(receipt['status'],'PASS')  # execution only
                self.assertEqual(receipt[field],'BLOCKED')
                self.assertEqual(report[items],[])
                self.assertIn('CATALOG_INVALID',[b['code'] for b in report['blockers']])
                self.assertFalse(report['dispatch_enabled'])
                self.assertEqual(receipt['input_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(receipt['output_sha256'],hashlib.sha256(output.read_bytes()).hexdigest())

    def job(self, output):
        return dict(tool='wholesale',operation='dry-run',mode='sandbox',
                    input=str(run.ROOT/'integrations/wholesale/sandbox-input.json'),output=str(output),
                    publication_enabled=False,paid_generation_enabled=False,live_enabled=False)

    def test_existing_worker_executes_real_node_cli_and_emits_matching_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/'report.json'
            receipt=run.run(self.job(output),root/'runtime')
            report=json.loads(output.read_text())
            self.assertEqual(receipt['status'],'PASS')
            self.assertFalse(receipt['provider_validated'])
            self.assertEqual(report['orders_placed'],0)
            self.assertEqual(receipt['output_sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual([o['state'] for o in report['state']['orders']],['refunded','cancelled','accepted'])
            with self.assertRaisesRegex(ValueError,'already exists'):
                run.run(self.job(output),root/'runtime')

    def test_existing_worker_rejects_unsafe_or_missing_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for change in ({'mode':'live'},{'operation':'publish'},{'publication_enabled':True},{'paid_generation_enabled':True},{'live_enabled':None}):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    run.run(self.job(root/'result.json')|change,root/'runtime')
            self.assertFalse((root/'result.json').exists())

    def test_existing_worker_executes_full_mock_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/'integration.json'
            receipt=run.run(self.job(output)|{'operation':'integration-dry-run'},root/'runtime')
            self.assertEqual(receipt['status'],'PASS')
            report=json.loads(output.read_text())
            self.assertEqual(len(report['state']['orders']),3)
            self.assertFalse(report['provider_validated'])

    def test_existing_worker_reports_offline_onboarding_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/'onboarding.json'
            job=self.job(output)|{'operation':'onboarding-check','input':str(run.ROOT/'integrations/wholesale/onboarding.example.json')}
            receipt=run.run(job,root/'runtime')
            report=json.loads(output.read_text())
            self.assertEqual(receipt['status'],'PASS') # execution succeeded, onboarding did not
            self.assertEqual(report['status'],'BLOCKED')
            self.assertEqual(receipt['onboarding_status'],'BLOCKED')
            self.assertFalse(report['production_ready'])
            self.assertIn('UNIQUE_SELLER_ACCOUNT_REQUIRED',[b['code'] for b in report['blockers']])

    def test_listing_draft_worker_preserves_blocked_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/'draft.json'
            job=self.job(output)|{'operation':'listing-draft','input':str(run.ROOT/'integrations/wholesale/onboarding.example.json')}
            receipt=run.run(job,root/'runtime')
            report=json.loads(output.read_text())
            self.assertEqual(receipt['status'],'PASS')
            self.assertEqual(receipt['draft_status'],'BLOCKED')
            self.assertEqual(report['drafts'],[])
            self.assertFalse(report['dispatch_enabled'])
            with self.assertRaisesRegex(ValueError,'already exists'):
                run.run(job,root/'runtime')

    def test_receipt_binds_consumed_bytes_when_source_changes_during_cli(self):
        for phase in ('before', 'after'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                source=root/'source.json'
                consumed=(run.ROOT/'integrations/wholesale/onboarding.example.json').read_bytes()
                source.write_bytes(consumed)
                output=root/'report.json'
                real_run=subprocess.run
                def mutate_source(*args, **kwargs):
                    if phase=='before': source.write_text('{"not_consumed_by_cli":true}')
                    result=real_run(*args, **kwargs)
                    if phase=='after': source.write_text('{"not_consumed_by_cli":true}')
                    return result
                with patch('subprocess.run',side_effect=mutate_source):
                    receipt=run.run(self.job(output)|dict(operation='offer-contract',input=str(source)),root/'runtime')
                self.assertEqual(receipt['contract_status'],'BLOCKED')
                self.assertEqual(receipt['input_sha256'],hashlib.sha256(consumed).hexdigest())
                self.assertNotEqual(receipt['input_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())

    def test_offer_contract_worker_runs_synthetic_preview_and_blocks_missing_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            authored=subprocess.run(['node','--input-type=module','-e',
                "import {fixture} from './integrations/wholesale/offer-contract.fixture.mjs'; console.log(JSON.stringify(fixture()));"],cwd=run.ROOT,capture_output=True,text=True,check=True)
            config=json.loads(authored.stdout)
            evidence=dict(classification='declared_document',reference='SYNTHETIC-ONLY',account_id='TEST-ACCOUNT',seller_sku='TEST-SELLER-SKU',category_id='123',observed_at_ms=config['now'],expires_at_ms=config['now']+1000)
            config['offer_contracts']=[dict(seller_sku='TEST-SELLER-SKU',listing_duration='GTC',shipping_mode='flat',identifiers={},
                reconciliation=evidence|dict(version='TEST-1',max_age_ms=1000,scope='single_offer_single_marketplace',pending_mutations=0,existing_offer_quantity=0,other_reserved_quantity=0,absolute_offer_quantity=1),
                category_requirements=evidence|dict(complete=True,required_aspects=['Brand'],required_identifiers=[],allowed_conditions=['NEW'],allowed_durations=['GTC'],unsupported_required_fields=[],package_required=False))]
            source=root/'input.json'
            for label,expected,count in [('complete','CONTRACT_PREVIEW_UNVERIFIED',1),('missing','BLOCKED',0)]:
                if label=='missing': config.pop('offer_contracts')
                source.write_text(json.dumps(config),encoding='utf-8')
                output=root/(label+'.json')
                job=self.job(output)|dict(operation='offer-contract',input=str(source))
                consumed=source.read_bytes()
                real_run=subprocess.run
                def replace_after_cli(*args, **kwargs):
                    result=real_run(*args, **kwargs)
                    source.write_text('{"not_consumed_by_cli":true}')
                    return result
                with patch('subprocess.run',side_effect=replace_after_cli):
                    receipt=run.run(job,root/'runtime')
                report=json.loads(output.read_text())
                self.assertEqual(receipt['input_sha256'],hashlib.sha256(consumed).hexdigest())
                self.assertNotEqual(receipt['input_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(receipt['status'],'PASS')
                self.assertEqual(receipt['contract_status'],expected)
                self.assertEqual(receipt['plan_count'],count)
                self.assertEqual(report['status'],expected)
                self.assertEqual(receipt['output_sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
                self.assertFalse(receipt['dispatch_enabled'])
                self.assertFalse(receipt['api_schema_validated'])
                with self.assertRaisesRegex(ValueError,'already exists'): run.run(job,root/'runtime')
            for flag in ('publication_enabled','paid_generation_enabled','live_enabled'):
                with self.assertRaises(ValueError):
                    run.run(self.job(root/'unsafe.json')|dict(operation='offer-contract')|{flag:True},root/'runtime')
            self.assertFalse((root/'unsafe.json').exists())

if __name__=='__main__':unittest.main()
