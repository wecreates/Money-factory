"""Bounded, fail-closed probe for an ordinary Chromium-compatible runtime.

This verifies only whether a selected local browser can render a data URL with
its normal sandbox intact.  It never installs a browser, opens a network URL,
weakens browser isolation, starts a persistent service, or claims that
OpenMontage/Remotion or a complete content-production consumer was exercised.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import tempfile
import time

if __package__:
    from integrations.owned_process import owned_process
else:  # Support the documented ``python integrations/<script>.py`` form.
    from owned_process import owned_process


MAX_OUTPUT_BYTES = 1024 * 1024
PROBE_MARKER = "CYZOR_BROWSER_RUNTIME_READY"
BROWSER_SCOPE = (
    "Current-host ordinary browser startup and local data-URL rendering only; "
    "no network page, provider, media consumer, Remotion render, creative review, "
    "publication, deployment, persistence, or 24-hour operation verified"
)
FORBIDDEN_ARGUMENTS = frozenset((
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-seccomp-filter-sandbox",
    "--disable-namespace-sandbox",
    "--single-process",
))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_fingerprint_sha256():
    """Return a non-secret stable hash used only to join same-host receipts."""
    components = [platform.node().encode("utf-8", errors="surrogateescape")]
    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            metadata = candidate.lstat()
            if stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 4096:
                value = candidate.read_bytes().strip()
                if value:
                    components.append(value)
                    break
        except OSError:
            continue
    if not any(components):
        raise ValueError("host_fingerprint_unavailable")
    return hashlib.sha256(b"\0".join(components)).hexdigest()


def resolve_browser(browser):
    """Return a regular, executable browser file without trusting shell lookup."""
    supplied = Path(browser)
    if not supplied.is_absolute():
        raise ValueError("browser_path_must_be_absolute")
    try:
        resolved = supplied.resolve(strict=True)
        metadata = resolved.stat()
    except (OSError, RuntimeError) as error:
        raise ValueError("browser_path_invalid") from error
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise ValueError("browser_not_executable_regular_file")
    return resolved


def build_command(browser, profile):
    command = [
        str(browser),
        "--headless",
        "--disable-gpu",
        f"--user-data-dir={profile}",
        "--dump-dom",
        f"data:text/html,<title>{PROBE_MARKER}</title><h1>{PROBE_MARKER}</h1>",
    ]
    if FORBIDDEN_ARGUMENTS.intersection(command):
        raise ValueError("sandbox_weakening_argument_forbidden")
    return command


def safe_environment(home):
    """Do not expose provider credentials, hooks, proxies, or caller profiles."""
    environment = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(Path(home) / "config"),
        "XDG_CACHE_HOME": str(Path(home) / "cache"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PUBLICATION_ENABLED": "false",
        "PAID_GENERATION_ENABLED": "false",
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def classify(exit_code, stdout, stderr, *, output_limited=False):
    diagnostic = stderr.decode("utf-8", errors="replace")
    if output_limited:
        return "BLOCKED_OUTPUT_LIMIT"
    if exit_code == 0 and PROBE_MARKER.encode() in stdout:
        return "ORDINARY_BROWSER_READY"
    if re.search(r"process_singleton.*socket\(\) failed: Operation not permitted", diagnostic,
                 flags=re.IGNORECASE | re.DOTALL):
        return "BLOCKED_PROCESS_SINGLETON_SOCKET_POLICY"
    if exit_code == 125:
        return "BLOCKED_TIMEOUT_OR_CANCELLED"
    return "BLOCKED_BROWSER_EXIT"


def probe(browser, *, timeout_seconds=30):
    if not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_out_of_bounds")
    executable = resolve_browser(browser)
    with tempfile.TemporaryDirectory(prefix="cyzor-browser-runtime-") as temporary:
        root = Path(temporary)
        profile = root / "profile"
        profile.mkdir(mode=0o700)
        command = build_command(executable, profile)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            with owned_process(command, timeout=timeout_seconds, env=safe_environment(root),
                               stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr) as process:
                output_limited = False
                while process.poll() is None:
                    if (os.fstat(stdout.fileno()).st_size > MAX_OUTPUT_BYTES or
                            os.fstat(stderr.fileno()).st_size > MAX_OUTPUT_BYTES):
                        output_limited = True
                        process.terminate()
                        break
                    time.sleep(0.02)
                process.wait()
                exit_code = process.returncode
            stdout.seek(0)
            stderr.seek(0)
            stdout_bytes = stdout.read(MAX_OUTPUT_BYTES + 1)
            stderr_bytes = stderr.read(MAX_OUTPUT_BYTES + 1)
    if len(stdout_bytes) > MAX_OUTPUT_BYTES or len(stderr_bytes) > MAX_OUTPUT_BYTES:
        output_limited = True
    status = classify(exit_code, stdout_bytes, stderr_bytes, output_limited=output_limited)
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "browser_binary_name": executable.name,
        "browser_binary_sha256": sha256_file(executable),
        "host_fingerprint_sha256": host_fingerprint_sha256(),
        # owned_process returns its guardian status; signal exits may be shell-normalized.
        "guardian_exit_code": exit_code,
        "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
        "timeout_seconds": timeout_seconds,
        "probe_target": "local_data_url",
        "ordinary_browser_runtime_verified": status == "ORDINARY_BROWSER_READY",
        "openmontage_render_verified": False,
        "browser_media_consumer_verified": False,
        "production_ready": False,
        "publication_enabled": False,
        "paid_generation_enabled": False,
        "sandbox_weakening_used": False,
        "scope": BROWSER_SCOPE,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", required=True,
                        help="Absolute path to an existing Chromium-compatible executable")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        report = probe(args.browser, timeout_seconds=args.timeout_seconds)
    except (OSError, ValueError, subprocess.SubprocessError):
        report = {
            "schema_version": 1,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED_PROBE_CONFIGURATION",
            "ordinary_browser_runtime_verified": False,
            "openmontage_render_verified": False,
            "browser_media_consumer_verified": False,
            "production_ready": False,
            "publication_enabled": False,
            "paid_generation_enabled": False,
            "sandbox_weakening_used": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ORDINARY_BROWSER_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
