import json
import os
from pathlib import Path
import tempfile
import unittest
from mcp_probe import probe, _manifest


class MCPProbeTests(unittest.TestCase):
    def test_rejects_linked_input(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'a.js').write_text('export const a=1;')
            (root/'link.js').symlink_to(root/'a.js')
            with self.assertRaisesRegex(ValueError, 'Linked'):
                _manifest(root)

    @unittest.skipUnless(os.environ.get('REA_RUNTIME'), 'Set REA_RUNTIME for real MCP verification')
    def test_real_mcp_source_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'index.js').write_text('import {value} from "./value.js"; throw Error("DO_NOT_EXECUTE");')
            (root/'value.js').write_text('export const value=42;')
            result=probe(os.environ['REA_RUNTIME'], root)
            self.assertEqual(result['initialize']['serverInfo']['version'], '6.4.0')
            self.assertIn('analyze_javascript_application', result['tool_names'])
            self.assertFalse(result['identity'].get('isError', False))
            self.assertFalse(result['production_ready'])
            if os.environ.get('REA_REQUIRE_PASS') == '1':
                self.assertEqual(result['status'], 'PASS', json.dumps(result.get('analysis')))
            elif result['status'] != 'PASS':
                self.assertTrue(result['analysis']['isError'])
                self.assertIn('procps-compatible ps', json.dumps(result['analysis']))
            else:
                self.assertTrue(result['analysis']['structuredContent']['evidence_id'])


if __name__ == '__main__':
    unittest.main()
