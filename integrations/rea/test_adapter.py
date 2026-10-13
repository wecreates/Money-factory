import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('rea_adapter',Path(__file__).with_name('adapter.py'))
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)


class StaticAnalysisTests(unittest.TestCase):
    def test_linked_target_is_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'linked').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError,'Linked'):
                adapter.analyze(root,root/'absent')

    @unittest.skipUnless(os.environ.get('REA_RUNTIME'),'Provide an installed pinned runtime for real execution')
    def test_actual_static_analysis_never_executes_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'main.js').write_text('import {add} from "./math.js"; throw Error("MUST NOT EXECUTE"); export const n=add(2,3);')
            (root/'math.js').write_text('export function add(a,b){return a+b;}')
            report=adapter.analyze(root,Path(os.environ['REA_RUNTIME']))
            self.assertEqual(len(report['input_sha256']),2)
            self.assertFalse(report['publication_enabled'])
            if report['status']=='PASS':
                self.assertIn('math.js',json.dumps(report['evidence']))
                self.assertEqual(report['exit_code'],0)
            else:
                if os.environ.get('REA_REQUIRE_PASS') == '1':
                    self.fail(json.dumps(report['evidence']))
                # Known workspace infrastructure limitation, never a false pass.
                self.assertEqual(report['evidence']['code'],'capability_unavailable')
                self.assertIn('procps-compatible ps',report['evidence']['message'])
                self.assertNotEqual(report['exit_code'],0)
                print('REA runtime BLOCKED: procps process ownership inspection unavailable; source inventory only.')


if __name__=='__main__': unittest.main()
