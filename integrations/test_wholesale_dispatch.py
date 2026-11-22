"""Shared runner compatibility; no upstream runtimes or provider calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import run


class DispatchCompatibility(unittest.TestCase):
    def test_nonwholesale_retains_lock_and_original_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'runtime'
            lock_api = Mock(LOCK_EX=2)
            job = {'tool': 'existing-tool'}
            with patch.object(run, 'fcntl', lock_api), patch.object(run, '_run', return_value='existing-result') as dispatch:
                self.assertEqual(run.run(job, runtime), 'existing-result')
                dispatch.assert_called_once_with(job, runtime)
                lock_api.flock.assert_called_once()

    def test_nonwholesale_without_posix_lock_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'not-created'
            with patch.object(run, 'fcntl', None), patch.object(run, '_run') as dispatch:
                with self.assertRaisesRegex(RuntimeError, 'POSIX file locking'):
                    run.run({'tool': 'existing-tool'}, runtime)
                dispatch.assert_not_called()
                self.assertFalse(runtime.exists())

    def test_wholesale_unsafe_flags_cannot_fall_back_to_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(run, '_run') as dispatch:
                with self.assertRaises(ValueError):
                    run.run({'tool': 'wholesale', 'operation': 'dry-run', 'mode': 'sandbox',
                             'publication_enabled': True}, Path(directory))
                dispatch.assert_not_called()
