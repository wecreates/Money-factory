"""Review routing tests: a diagnostic result never grants a review attestation."""
import contextlib
import io
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_review import main


class ReviewCLITests(unittest.TestCase):
    def call(self, args):
        with patch('sys.argv', ['cycle_review', *args]), contextlib.redirect_stdout(io.StringIO()):
            return main()

    def test_analysis_routes_to_existing_candidate_and_new_output(self):
        args=['--cycle-dir','/cycle','--output','/diagnostic','--analyze',
              '--rea-runtime','/runtime/bin/python','--timeout','60']
        with patch('integrations.rea_video.analyze_cycle.analyze_cycle', return_value={'status':'DIAGNOSTIC_COMPLETE'}) as analyze:
            self.assertEqual(self.call(args),0)
            analyze.assert_called_once_with('/cycle','/diagnostic',runtime='/runtime/bin/python',timeout=60)
        with patch('integrations.rea_video.analyze_cycle.analyze_cycle', return_value={'status':'BLOCKED'}):
            self.assertEqual(self.call(args),2)

    def test_analysis_cannot_be_used_as_a_review_or_revision(self):
        base=['--cycle-dir','/cycle','--output','/diagnostic']
        for tail in ([], ['--analyze'], ['--analyze','--rea-runtime','/python','--review','/review'],
                     ['--analyze','--rea-runtime','/python','--revision-brief','/brief'],
                     ['--review','/review','--rea-runtime','/python'],
                     ['--analyze','--rea-runtime','/python','--rea-analysis','/analysis.json'],
                     ['--review','/review','--revision-brief','/brief','--rea-analysis','/analysis.json']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                self.call(base+tail)
            self.assertEqual(raised.exception.code,2)

    def test_existing_review_route_is_preserved(self):
        with patch('integrations.content_control.cycle_review.record_review',return_value={'status':'REVISION_REQUIRED'}) as review:
            self.assertEqual(self.call(['--cycle-dir','/cycle','--review','/review','--output','/record']),0)
            review.assert_called_once_with('/cycle','/review','/record')

    def test_review_option_links_rea_analysis(self):
        with patch('integrations.content_control.cycle_review.record_review',
                   return_value={'status':'REVISION_REQUIRED'}) as review:
            args = ['--cycle-dir','/cycle','--review','/review','--output','/record',
                    '--rea-analysis','/analysis.json']
            self.assertEqual(self.call(args), 0)
            review.assert_called_once_with('/cycle','/review','/record',rea_analysis='/analysis.json')

    def test_package_lint_is_separate_from_attestation_and_rea(self):
        args = ['--cycle-dir', '/cycle', '--output', '/lint', '--package-lint']
        with patch('integrations.content_control.cycle_review.lint_package',
                   return_value={'status': 'DIAGNOSTIC_COMPLETE'}) as lint:
            self.assertEqual(self.call(args), 0)
            lint.assert_called_once_with('/cycle', '/lint')
            for tail in (['--analyze'], ['--review', '/review'], ['--revision-brief', '/brief'], ['--rea-runtime', '/python']):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    self.call(args + tail)


if __name__=='__main__':
    unittest.main()
