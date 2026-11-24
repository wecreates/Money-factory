import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations import browser_runtime_probe as browser_probe


class BrowserRuntimeProbeTests(unittest.TestCase):
    def test_command_uses_only_ordinary_flags_and_local_data_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            command = browser_probe.build_command(Path("/usr/bin/chromium"), Path(temporary))
        self.assertTrue(command[-1].startswith("data:text/html,"))
        self.assertTrue(browser_probe.FORBIDDEN_ARGUMENTS.isdisjoint(command))
        self.assertFalse(any(argument.startswith("http://") or argument.startswith("https://")
                             for argument in command))
        self.assertFalse(any("remote-debugging" in argument for argument in command))

    def test_status_requires_success_and_rendered_marker(self):
        marker = browser_probe.PROBE_MARKER.encode()
        self.assertEqual(browser_probe.classify(0, marker, b""), "ORDINARY_BROWSER_READY")
        self.assertEqual(browser_probe.classify(0, b"", b""), "BLOCKED_BROWSER_EXIT")
        self.assertEqual(browser_probe.classify(1, marker, b""), "BLOCKED_BROWSER_EXIT")

    def test_known_socket_policy_failure_is_distinct(self):
        error = (b"FATAL:process_singleton_posix.cc:297] Check failed: . "
                 b"socket() failed: Operation not permitted (1)")
        self.assertEqual(
            browser_probe.classify(134, b"", error),
            "BLOCKED_PROCESS_SINGLETON_SOCKET_POLICY",
        )

    def test_output_limit_and_timeout_fail_closed(self):
        self.assertEqual(
            browser_probe.classify(0, browser_probe.PROBE_MARKER.encode(), b"", output_limited=True),
            "BLOCKED_OUTPUT_LIMIT",
        )
        self.assertEqual(browser_probe.classify(125, b"", b""), "BLOCKED_TIMEOUT_OR_CANCELLED")

    def test_browser_must_be_absolute_existing_executable(self):
        with self.assertRaisesRegex(ValueError, "browser_path_must_be_absolute"):
            browser_probe.resolve_browser("chromium")
        with self.assertRaisesRegex(ValueError, "browser_path_invalid"):
            browser_probe.resolve_browser("/definitely/not/a/browser")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "browser"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            self.assertEqual(browser_probe.resolve_browser(executable), executable)

    def test_environment_drops_credentials_proxies_and_runtime_hooks(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "OPENAI_API_KEY": "secret",
            "HTTP_PROXY": "http://proxy.invalid",
            "NODE_OPTIONS": "--require bad",
            "PYTHONPATH": "/untrusted",
        }):
            environment = browser_probe.safe_environment(temporary)
        self.assertTrue({"OPENAI_API_KEY", "HTTP_PROXY", "NODE_OPTIONS", "PYTHONPATH"}.isdisjoint(environment))
        self.assertEqual(environment["PUBLICATION_ENABLED"], "false")
        self.assertEqual(environment["PAID_GENERATION_ENABLED"], "false")

    def test_configuration_failure_receipt_does_not_expose_input_path(self):
        with patch("builtins.print") as output:
            self.assertEqual(browser_probe.main(["--browser", "/secret/missing/browser"]), 2)
        receipt = output.call_args.args[0]
        self.assertNotIn("/secret", receipt)
        self.assertIn("BLOCKED_PROBE_CONFIGURATION", receipt)
        self.assertIn('"publication_enabled": false', receipt)


if __name__ == "__main__":
    unittest.main()
