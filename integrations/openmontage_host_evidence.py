"""Fail-closed verification of an intended-host OpenMontage render bundle.

This module does not run or install OpenMontage.  It verifies a retained receipt
against a clean checkout at the expected commit, an ordinary-browser preflight,
the exact input/output media, and an independent ffprobe observation.  The
result binds a host-run claim; it is not creative approval or a 24-hour proof.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time

try:
    from integrations.browser_runtime_probe import BROWSER_SCOPE
except ImportError:  # Support ``python integrations/<script>.py``.
    from browser_runtime_probe import BROWSER_SCOPE


PIN = "2e003e65fa99a0f329478a2c1cdcf26bc481933a"
SOURCE_URL = "https://github.com/OpenMontageInc/OpenMontage"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
MAX_JSON = 1024 * 1024
MAX_LOG = 4 * 1024 * 1024
MAX_MEDIA = 512 * 1024 * 1024
MAX_CLOCK_SKEW_SECONDS = 300
BROWSER_RECEIPT_FIELDS = {
    "schema_version", "observed_at", "status", "browser_binary_name",
    "browser_binary_sha256", "host_fingerprint_sha256", "guardian_exit_code",
    "stdout_sha256", "stderr_sha256", "timeout_seconds", "probe_target",
    "ordinary_browser_runtime_verified", "openmontage_render_verified",
    "browser_media_consumer_verified", "production_ready", "publication_enabled",
    "paid_generation_enabled", "sandbox_weakening_used", "scope",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _hex64(value):
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _sha256(path, *, limit=None):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if limit is not None:
                _require(size <= limit, "file_size_limit_exceeded")
            digest.update(chunk)
    return digest.hexdigest(), size


def _regular(path, *, limit=None):
    _require(path.is_absolute(), "absolute_path_required")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError("required_file_unavailable") from error
    _require(stat.S_ISREG(metadata.st_mode), "regular_file_required")
    if limit is not None:
        _require(metadata.st_size <= limit, "file_size_limit_exceeded")
    return path


def _json(path):
    raw = _regular(path, limit=MAX_JSON).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_json") from error
    _require(isinstance(value, dict), "json_object_required")
    return value, hashlib.sha256(raw).hexdigest()


def _child(root, name, *, limit=None):
    _require(isinstance(name, str) and name and Path(name).name == name,
             "bundle_filename_required")
    return _regular(root / name, limit=limit)


def _timestamp(value, field):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(field + "_invalid") from error
    _require(parsed.tzinfo is not None, field + "_timezone_required")
    return parsed.astimezone(timezone.utc)


def _stop_process(process):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass


def _run(command, *, timeout=30):
    _require(type(timeout) in (int, float) and not isinstance(timeout, bool)
             and 0 < timeout <= 60, "verification_timeout_invalid")
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                start_new_session=os.name == "posix",
            )
            deadline = time.monotonic() + timeout
            limited = False
            while process.poll() is None:
                if (os.fstat(stdout.fileno()).st_size > MAX_JSON
                        or os.fstat(stderr.fileno()).st_size > MAX_JSON):
                    limited = True
                    _stop_process(process)
                    break
                if time.monotonic() >= deadline:
                    _stop_process(process)
                    raise ValueError("verification_command_timeout")
                time.sleep(0.02)
            process.wait(timeout=2)
            stdout.seek(0)
            stderr.seek(0)
            stdout_bytes = stdout.read(MAX_JSON + 1)
            stderr_bytes = stderr.read(MAX_JSON + 1)
            limited = limited or len(stdout_bytes) > MAX_JSON or len(stderr_bytes) > MAX_JSON
            return_code = process.returncode
    except ValueError:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("verification_command_failed") from error
    _require(not limited, "verification_output_limit_exceeded")
    _require(return_code == 0, "verification_command_nonzero")
    return stdout_bytes


def _source_identity(source_root, expected_commit):
    root = Path(source_root)
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
             "absolute_source_directory_required")
    head = _run(["git", "-C", str(root), "rev-parse", "HEAD"]).decode().strip()
    _require(head == expected_commit, "source_commit_mismatch")
    remote = _run(["git", "-C", str(root), "remote", "get-url", "origin"]).decode().strip()
    _require(remote.rstrip("/").removesuffix(".git") == SOURCE_URL,
             "source_remote_not_canonical")
    status = _run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"])
    _require(not status.strip(), "source_checkout_not_clean")
    return root


def _snapshot(source, destination, *, limit, executable=False):
    source = _regular(Path(source), limit=limit)
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream, destination.open("xb") as output:
            metadata = os.fstat(stream.fileno())
            _require(stat.S_ISREG(metadata.st_mode), "regular_file_required")
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                _require(size <= limit, "file_size_limit_exceeded")
                digest.update(chunk)
                output.write(chunk)
    except OSError as error:
        raise ValueError("snapshot_failed") from error
    destination.chmod(0o500 if executable else 0o400)
    return digest.hexdigest(), size


def _probe_media(ffprobe, media, *, expected_media_sha256=None):
    executable = _regular(Path(ffprobe))
    _require(os.access(executable, os.X_OK), "ffprobe_not_executable")
    with tempfile.TemporaryDirectory(prefix="cyzor-media-probe-") as temporary:
        root = Path(temporary)
        executable_snapshot = root / ("verifier-" + executable.name)
        media_snapshot = root / ("candidate" + Path(media).suffix)
        executable_sha, _ = _snapshot(executable, executable_snapshot,
                                      limit=MAX_MEDIA, executable=True)
        media_sha, media_bytes = _snapshot(media, media_snapshot, limit=MAX_MEDIA)
        if expected_media_sha256 is not None:
            _require(media_sha == expected_media_sha256, "output_media_identity_mismatch")
        raw = _run([
            str(executable_snapshot), "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,duration",
            "-of", "json", str(media_snapshot),
        ], timeout=60)
        executable_after, _ = _sha256(executable_snapshot, limit=MAX_MEDIA)
        media_after, _ = _sha256(media_snapshot, limit=MAX_MEDIA)
        _require(executable_after == executable_sha, "ffprobe_changed_during_probe")
        _require(media_after == media_sha, "output_changed_during_probe")
    try:
        observation = json.loads(raw)
        duration = float(observation["format"]["duration"])
        streams = observation["streams"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("ffprobe_observation_invalid") from error
    _require(math.isfinite(duration) and 0.5 <= duration <= 3600,
             "output_duration_invalid")
    _require(isinstance(streams, list), "output_streams_invalid")
    kinds = {stream.get("codec_type") for stream in streams if isinstance(stream, dict)}
    _require({"video", "audio"}.issubset(kinds), "output_requires_video_and_audio")
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    _require(type(video.get("width")) is int and 0 < video["width"] <= 8192
             and type(video.get("height")) is int and 0 < video["height"] <= 8192,
             "output_dimensions_invalid")
    return {
        "duration_seconds": duration,
        "stream_types": sorted(kinds),
        "video_codec": video.get("codec_name"),
        "width": video["width"],
        "height": video["height"],
        "ffprobe_sha256": executable_sha,
        "media_sha256": media_sha,
        "media_bytes": media_bytes,
    }


def _validate_browser_receipt(browser, host_fingerprint):
    _require(set(browser) == BROWSER_RECEIPT_FIELDS, "browser_receipt_schema_mismatch")
    _require(type(browser["schema_version"]) is int and browser["schema_version"] == 1,
             "browser_schema_version_invalid")
    _require(browser["status"] == "ORDINARY_BROWSER_READY"
             and browser["ordinary_browser_runtime_verified"] is True
             and browser["openmontage_render_verified"] is False
             and browser["browser_media_consumer_verified"] is False
             and browser["production_ready"] is False
             and browser["publication_enabled"] is False
             and browser["paid_generation_enabled"] is False
             and browser["sandbox_weakening_used"] is False,
             "ordinary_browser_preflight_required")
    _require(_hex64(host_fingerprint)
             and browser["host_fingerprint_sha256"] == host_fingerprint,
             "browser_host_fingerprint_mismatch")
    _require(isinstance(browser["browser_binary_name"], str)
             and browser["browser_binary_name"]
             and Path(browser["browser_binary_name"]).name == browser["browser_binary_name"],
             "browser_binary_name_invalid")
    for field in ("browser_binary_sha256", "stdout_sha256", "stderr_sha256"):
        _require(_hex64(browser[field]),
                 field + "_invalid")
    _require(type(browser["guardian_exit_code"]) is int
             and browser["guardian_exit_code"] == 0,
             "browser_guardian_exit_invalid")
    _require(type(browser["timeout_seconds"]) is int
             and 1 <= browser["timeout_seconds"] <= 60,
             "browser_timeout_invalid")
    _require(browser["probe_target"] == "local_data_url"
             and browser["scope"] == BROWSER_SCOPE,
             "browser_probe_contract_invalid")


def verify(bundle_root, source_root, ffprobe, expected_commit=PIN):
    _require(isinstance(expected_commit, str)
             and HEX40.fullmatch(expected_commit) is not None,
             "expected_commit_invalid")
    root = Path(bundle_root)
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
             "absolute_bundle_directory_required")
    source = _source_identity(source_root, expected_commit)
    receipt, receipt_sha = _json(_child(root, "consumer-receipt.json", limit=MAX_JSON))

    required = {
        "schema_version", "consumer", "operation", "source_url", "source_commit",
        "started_at", "finished_at", "host_fingerprint_sha256", "entrypoint",
        "entrypoint_sha256", "browser_receipt", "browser_receipt_sha256",
        "input_media", "input_media_sha256", "output_media", "output_media_sha256",
        "execution_log", "execution_log_sha256", "process_exit_code",
        "full_application_render_completed", "remotion_render_completed",
        "provider_calls", "publication_enabled", "paid_generation_enabled",
        "sandbox_weakening_used",
    }
    _require(set(receipt) == required, "consumer_receipt_schema_mismatch")
    _require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
             and receipt["consumer"] == "openmontage"
             and receipt["operation"] == "openmontage_full_application_render",
             "consumer_identity_mismatch")
    _require(receipt["source_url"] == SOURCE_URL and receipt["source_commit"] == expected_commit,
             "canonical_source_mismatch")
    _require(_hex64(receipt.get("host_fingerprint_sha256")),
             "host_fingerprint_invalid")
    started = _timestamp(receipt["started_at"], "started_at")
    finished = _timestamp(receipt["finished_at"], "finished_at")
    now = datetime.now(timezone.utc)
    _require(started < finished and (finished - started).total_seconds() <= 3600,
             "execution_window_invalid")
    _require(finished <= now
             or (finished - now).total_seconds() <= MAX_CLOCK_SKEW_SECONDS,
             "execution_timestamp_in_future")
    _require(type(receipt["process_exit_code"]) is int
             and receipt["process_exit_code"] == 0
             and receipt["full_application_render_completed"] is True
             and receipt["remotion_render_completed"] is True,
             "successful_full_render_required")
    _require(type(receipt["provider_calls"]) is int
             and receipt["provider_calls"] == 0
             and receipt["publication_enabled"] is False
             and receipt["paid_generation_enabled"] is False
             and receipt["sandbox_weakening_used"] is False,
             "safety_scope_mismatch")

    entrypoint_name = receipt["entrypoint"]
    _require(isinstance(entrypoint_name, str) and entrypoint_name
             and not Path(entrypoint_name).is_absolute() and ".." not in Path(entrypoint_name).parts,
             "entrypoint_path_invalid")
    supplied_entrypoint = _regular(source / entrypoint_name, limit=MAX_JSON)
    entrypoint = supplied_entrypoint.resolve()
    _require(entrypoint.is_relative_to(source.resolve()), "entrypoint_outside_source")
    entrypoint_sha, _ = _sha256(entrypoint, limit=MAX_JSON)
    _require(_hex64(receipt["entrypoint_sha256"])
             and entrypoint_sha == receipt["entrypoint_sha256"],
             "entrypoint_identity_mismatch")

    browser_path = _child(root, receipt["browser_receipt"], limit=MAX_JSON)
    browser, browser_sha = _json(browser_path)
    _require(browser_sha == receipt["browser_receipt_sha256"], "browser_receipt_hash_mismatch")
    _validate_browser_receipt(browser, receipt["host_fingerprint_sha256"])
    observed = _timestamp(browser.get("observed_at"), "browser_observed_at")
    preflight_age = (started - observed).total_seconds()
    _require(-MAX_CLOCK_SKEW_SECONDS <= preflight_age <= 3600,
             "browser_preflight_not_fresh")
    _require(observed <= now or (observed - now).total_seconds() <= MAX_CLOCK_SKEW_SECONDS,
             "browser_timestamp_in_future")

    identities = {}
    input_path = _child(root, receipt["input_media"], limit=MAX_MEDIA)
    input_expected = receipt["input_media_sha256"]
    input_sha, input_bytes = _sha256(input_path, limit=MAX_MEDIA)
    _require(_hex64(input_expected) and input_sha == input_expected,
             "input_media_identity_mismatch")
    identities["input"] = {
        "file": input_path.name, "sha256": input_expected, "bytes": input_bytes,
    }
    output_path = _child(root, receipt["output_media"], limit=MAX_MEDIA)
    output_expected = receipt["output_media_sha256"]
    _require(_hex64(output_expected),
             "output_media_identity_mismatch")
    output_before, output_bytes = _sha256(output_path, limit=MAX_MEDIA)
    _require(output_before == output_expected, "output_media_identity_mismatch")
    media = _probe_media(ffprobe, output_path, expected_media_sha256=output_expected)
    output_after, output_after_bytes = _sha256(output_path, limit=MAX_MEDIA)
    _require(output_after == output_expected and output_after_bytes == output_bytes
             and media.get("media_sha256") == output_expected
             and media.get("media_bytes") == output_bytes,
             "output_changed_during_probe")
    identities["output"] = {
        "file": output_path.name, "sha256": output_expected, "bytes": output_bytes,
    }
    _require(identities["input"]["sha256"] != identities["output"]["sha256"],
             "output_must_differ_from_input")

    log = _child(root, receipt["execution_log"], limit=MAX_LOG)
    log_sha, log_bytes = _sha256(log, limit=MAX_LOG)
    _require(log_bytes > 0 and _hex64(receipt["execution_log_sha256"])
             and log_sha == receipt["execution_log_sha256"],
             "execution_log_identity_mismatch")
    return {
        "schema_version": 1,
        "status": "OPENMONTAGE_HOST_EVIDENCE_BOUND",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_url": SOURCE_URL,
        "source_commit": expected_commit,
        "host_fingerprint_sha256": receipt["host_fingerprint_sha256"],
        "consumer_receipt_sha256": receipt_sha,
        "browser_receipt_sha256": browser_sha,
        "input": identities["input"],
        "output": identities["output"],
        "output_observation": media,
        "ordinary_browser_runtime_verified": True,
        "openmontage_render_claim_bound": True,
        "publication_enabled": False,
        "paid_generation_enabled": False,
        "sandbox_weakening_used": False,
        "creative_acceptance_verified": False,
        "full_av_review_verified": False,
        "actual_host_ownership_verified": False,
        "soak_24h_verified": False,
        "scope": (
            "Binds a retained intended-host OpenMontage/Remotion process receipt to a clean "
            "canonical checkout, fresh ordinary-browser preflight, exact media, log, and "
            "independent container observation. It does not independently observe the process, "
            "prove host ownership, or establish creative/full-AV/24-hour acceptance."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--expected-commit", default=PIN)
    args = parser.parse_args(argv)
    try:
        result = verify(Path(args.bundle_root).absolute(), Path(args.source_root).absolute(),
                        Path(args.ffprobe).absolute(), args.expected_commit)
    except (OSError, ValueError) as error:
        result = {
            "schema_version": 1,
            "status": "BLOCKED_OPENMONTAGE_HOST_EVIDENCE",
            "reason": str(error),
            "publication_enabled": False,
            "paid_generation_enabled": False,
            "sandbox_weakening_used": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "OPENMONTAGE_HOST_EVIDENCE_BOUND" else 2


if __name__ == "__main__":
    raise SystemExit(main())
