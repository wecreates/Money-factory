import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations import openmontage_host_evidence as verifier


probe_media = verifier._probe_media
source_identity = verifier._source_identity


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OpenMontageHostEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.bundle = root / "bundle"
        self.source = root / "source"
        self.bundle.mkdir()
        self.source.mkdir()
        (self.source / "package.json").write_text('{"scripts":{"render":"example"}}')
        (self.bundle / "input.mp4").write_bytes(b"input-media")
        (self.bundle / "output.mp4").write_bytes(b"output-media")
        (self.bundle / "execution.log").write_text("render completed\n")
        now = datetime.now(timezone.utc)
        self.observed_at = now - timedelta(minutes=10)
        self.started_at = now - timedelta(minutes=5)
        self.finished_at = now - timedelta(minutes=1)
        self.host_fingerprint = "a" * 64
        browser = {
            "schema_version": 1,
            "observed_at": self.observed_at.isoformat(),
            "status": "ORDINARY_BROWSER_READY",
            "browser_binary_name": "chromium",
            "browser_binary_sha256": "b" * 64,
            "host_fingerprint_sha256": self.host_fingerprint,
            "guardian_exit_code": 0,
            "stdout_sha256": "c" * 64,
            "stderr_sha256": "d" * 64,
            "timeout_seconds": 30,
            "probe_target": "local_data_url",
            "ordinary_browser_runtime_verified": True,
            "openmontage_render_verified": False,
            "browser_media_consumer_verified": False,
            "production_ready": False,
            "sandbox_weakening_used": False,
            "publication_enabled": False,
            "paid_generation_enabled": False,
            "scope": verifier.BROWSER_SCOPE,
        }
        (self.bundle / "browser.json").write_text(json.dumps(browser, sort_keys=True))
        self.receipt = {
            "schema_version": 1,
            "consumer": "openmontage",
            "operation": "openmontage_full_application_render",
            "source_url": verifier.SOURCE_URL,
            "source_commit": verifier.PIN,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "host_fingerprint_sha256": self.host_fingerprint,
            "entrypoint": "package.json",
            "entrypoint_sha256": digest(self.source / "package.json"),
            "browser_receipt": "browser.json",
            "browser_receipt_sha256": digest(self.bundle / "browser.json"),
            "input_media": "input.mp4",
            "input_media_sha256": digest(self.bundle / "input.mp4"),
            "output_media": "output.mp4",
            "output_media_sha256": digest(self.bundle / "output.mp4"),
            "execution_log": "execution.log",
            "execution_log_sha256": digest(self.bundle / "execution.log"),
            "process_exit_code": 0,
            "full_application_render_completed": True,
            "remotion_render_completed": True,
            "provider_calls": 0,
            "publication_enabled": False,
            "paid_generation_enabled": False,
            "sandbox_weakening_used": False,
        }
        self.write_receipt()
        self.source_patch = patch.object(verifier, "_source_identity", return_value=self.source)
        def media_result(_ffprobe, media, **_kwargs):
            return {
                "duration_seconds": 10.0, "stream_types": ["audio", "video"],
                "video_codec": "h264", "width": 720, "height": 1280,
                "ffprobe_sha256": "f" * 64,
                "media_sha256": digest(Path(media)),
                "media_bytes": Path(media).stat().st_size,
            }

        self.media_patch = patch.object(verifier, "_probe_media", side_effect=media_result)
        self.source_patch.start()
        self.media_patch.start()

    def tearDown(self):
        self.media_patch.stop()
        self.source_patch.stop()
        self.temporary.cleanup()

    def write_receipt(self):
        (self.bundle / "consumer-receipt.json").write_text(json.dumps(self.receipt, sort_keys=True))

    def verify(self):
        return verifier.verify(self.bundle.absolute(), self.source.absolute(), Path("/bin/true"), verifier.PIN)

    def test_binds_exact_safe_host_evidence_without_overclaiming(self):
        result = self.verify()
        self.assertEqual(result["status"], "OPENMONTAGE_HOST_EVIDENCE_BOUND")
        self.assertTrue(result["ordinary_browser_runtime_verified"])
        self.assertTrue(result["openmontage_render_claim_bound"])
        self.assertFalse(result["creative_acceptance_verified"])
        self.assertFalse(result["actual_host_ownership_verified"])
        self.assertFalse(result["soak_24h_verified"])

    def test_rejects_blocked_browser_and_stale_preflight(self):
        path = self.bundle / "browser.json"
        browser = json.loads(path.read_text())
        browser["status"] = "BLOCKED_PROCESS_SINGLETON_SOCKET_POLICY"
        browser["ordinary_browser_runtime_verified"] = False
        path.write_text(json.dumps(browser, sort_keys=True))
        self.receipt["browser_receipt_sha256"] = digest(path)
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "ordinary_browser_preflight_required"):
            self.verify()

        browser["status"] = "ORDINARY_BROWSER_READY"
        browser["ordinary_browser_runtime_verified"] = True
        browser["observed_at"] = (self.started_at - timedelta(hours=2)).isoformat()
        path.write_text(json.dumps(browser, sort_keys=True))
        self.receipt["browser_receipt_sha256"] = digest(path)
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "browser_preflight_not_fresh"):
            self.verify()

    def test_rejects_safety_relaxation_or_noncanonical_source(self):
        for key, value, message in (
            ("sandbox_weakening_used", True, "safety_scope_mismatch"),
            ("provider_calls", 1, "safety_scope_mismatch"),
            ("publication_enabled", True, "safety_scope_mismatch"),
            ("source_url", "https://example.invalid/fork", "canonical_source_mismatch"),
        ):
            original = self.receipt[key]
            self.receipt[key] = value
            self.write_receipt()
            with self.assertRaisesRegex(ValueError, message):
                self.verify()
            self.receipt[key] = original

    def test_rejects_forged_browser_schema_and_cross_host_receipt(self):
        path = self.bundle / "browser.json"
        browser = json.loads(path.read_text())
        browser.pop("stdout_sha256")
        path.write_text(json.dumps(browser, sort_keys=True))
        self.receipt["browser_receipt_sha256"] = digest(path)
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "browser_receipt_schema_mismatch"):
            self.verify()

        browser["stdout_sha256"] = "c" * 64
        browser["host_fingerprint_sha256"] = "e" * 64
        path.write_text(json.dumps(browser, sort_keys=True))
        self.receipt["browser_receipt_sha256"] = digest(path)
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "browser_host_fingerprint_mismatch"):
            self.verify()

    def test_rejects_future_evidence_and_boolean_integer_aliases(self):
        self.receipt["started_at"] = "2099-01-01T00:00:00+00:00"
        self.receipt["finished_at"] = "2099-01-01T00:01:00+00:00"
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "execution_timestamp_in_future"):
            self.verify()

        self.receipt["started_at"] = self.started_at.isoformat()
        self.receipt["finished_at"] = self.finished_at.isoformat()
        for field, value, message in (
            ("schema_version", True, "consumer_identity_mismatch"),
            ("process_exit_code", False, "successful_full_render_required"),
            ("provider_calls", False, "safety_scope_mismatch"),
        ):
            original = self.receipt[field]
            self.receipt[field] = value
            self.write_receipt()
            with self.assertRaisesRegex(ValueError, message):
                self.verify()
            self.receipt[field] = original

    def test_rejects_changed_media_log_entrypoint_and_extra_fields(self):
        cases = (
            (self.bundle / "output.mp4", b"changed", "output_media_identity_mismatch"),
            (self.bundle / "execution.log", b"changed", "execution_log_identity_mismatch"),
            (self.source / "package.json", b"changed", "entrypoint_identity_mismatch"),
        )
        for path, changed, message in cases:
            original = path.read_bytes()
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, message):
                self.verify()
            path.write_bytes(original)
        self.receipt["unexpected"] = True
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "consumer_receipt_schema_mismatch"):
            self.verify()

    def test_rejects_output_mutation_between_identity_and_probe(self):
        expected = self.receipt["output_media_sha256"]

        def mutate(_ffprobe, media, **_kwargs):
            Path(media).write_bytes(b"mutated-during-probe")
            return {
                "duration_seconds": 10.0, "stream_types": ["audio", "video"],
                "video_codec": "h264", "width": 720, "height": 1280,
                "ffprobe_sha256": "f" * 64, "media_sha256": expected,
                "media_bytes": len(b"output-media"),
            }

        with patch.object(verifier, "_probe_media", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "output_changed_during_probe"):
                self.verify()

    def test_rejects_same_input_output_identity_and_failed_process(self):
        self.receipt["output_media_sha256"] = self.receipt["input_media_sha256"]
        (self.bundle / "output.mp4").write_bytes((self.bundle / "input.mp4").read_bytes())
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "output_must_differ_from_input"):
            self.verify()

        (self.bundle / "output.mp4").write_bytes(b"output-media")
        self.receipt["output_media_sha256"] = digest(self.bundle / "output.mp4")
        self.receipt["process_exit_code"] = 1
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "successful_full_render_required"):
            self.verify()

    def test_media_probe_requires_audio_video_and_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ffprobe"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            media = Path(temporary) / "video.mp4"
            media.write_bytes(b"x")
            good = {"format": {"duration": "1.5"}, "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
                {"codec_type": "audio", "codec_name": "aac"},
            ]}
            with patch.object(verifier, "_run", return_value=json.dumps(good).encode()):
                self.assertEqual(probe_media(executable, media)["width"], 720)
            missing_audio = copy.deepcopy(good)
            missing_audio["streams"] = missing_audio["streams"][:1]
            with patch.object(verifier, "_run", return_value=json.dumps(missing_audio).encode()):
                with self.assertRaisesRegex(ValueError, "output_requires_video_and_audio"):
                    probe_media(executable, media)

    def test_media_probe_detects_mutating_ffprobe_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ffprobe"
            executable.write_text(
                "#!/bin/sh\n"
                "chmod u+w \"$0\"\n"
                "printf '# mutation\\n' >> \"$0\"\n"
                "printf '%s' '{\"format\":{\"duration\":\"1.5\"},\"streams\":["
                "{\"codec_type\":\"video\",\"codec_name\":\"h264\",\"width\":720,\"height\":1280},"
                "{\"codec_type\":\"audio\",\"codec_name\":\"aac\"}]}'\n"
            )
            executable.chmod(0o700)
            media = Path(temporary) / "video.mp4"
            media.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "ffprobe_changed_during_probe"):
                probe_media(executable, media)

    def test_subprocess_capture_stops_at_output_limit(self):
        with self.assertRaisesRegex(ValueError, "verification_output_limit_exceeded"):
            verifier._run([
                sys.executable, "-c",
                "import sys; sys.stdout.write('x' * (1024 * 1024 + 8192))",
            ])

    def test_source_identity_requires_clean_canonical_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            responses = iter([
                (verifier.PIN + "\n").encode(),
                (verifier.SOURCE_URL + ".git\n").encode(),
                b"",
            ])
            with patch.object(verifier, "_run", side_effect=lambda *args, **kwargs: next(responses)):
                self.assertEqual(source_identity(root, verifier.PIN), root)

            responses = iter([
                (verifier.PIN + "\n").encode(),
                b"https://example.invalid/fork.git\n",
            ])
            with patch.object(verifier, "_run", side_effect=lambda *args, **kwargs: next(responses)):
                with self.assertRaisesRegex(ValueError, "source_remote_not_canonical"):
                    source_identity(root, verifier.PIN)


if __name__ == "__main__":
    unittest.main()
