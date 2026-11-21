"""POSIX child guardian for trusted local agent executables, not an OS sandbox.

The adapter owns a pipe writer. Its guardian owns the reader and an optional
duplicate admission lease. Parent death closes the writer, so cleanup does not
depend on Python finally blocks. Workers never receive these descriptors.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

_writers = {}
_cancelled = False


def _close_writer(token):
    fd = _writers.pop(token, None)
    if fd is not None:
        os.close(fd)


@contextmanager
def interruptible_processes():
    """Cancel owned guardians before a foreground batch waits for its threads."""
    global _cancelled
    previous = {}
    prior_cancelled = _cancelled
    _cancelled = False
    def interrupted(signum, frame):
        global _cancelled
        # A second Ctrl-C/TERM must not interrupt the cleanup wait and release
        # the parent's explicit flock before its guardians have exited.
        if _cancelled:
            return
        _cancelled = True
        for token in list(_writers):
            _close_writer(token)
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, interrupted)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        _cancelled = prior_cancelled


@contextmanager
def owned_process(argv, *, timeout, lease_fd=None, **kwargs):
    """Yield a Popen-compatible guardian; wait for owned-group cleanup on exit.

    Native Windows retains direct-process cleanup only. The common worker
    runbook uses Linux/WSL2; no Windows parent-death/tree guarantee is claimed.
    """
    if _cancelled:
        raise InterruptedError('Agent batch was interrupted')
    if os.name == 'nt':
        process = subprocess.Popen(argv, **kwargs)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        return
    reader, writer = os.pipe()
    token = object()
    _writers[token] = writer
    process = None
    inherited = (reader,) if lease_fd is None else (reader, lease_fd)
    command = [sys.executable, str(Path(__file__).resolve()), str(reader), str(timeout), '--', *argv]
    try:
        if _cancelled:
            raise InterruptedError('Agent batch was interrupted')
        process = subprocess.Popen(command, pass_fds=inherited, start_new_session=True, **kwargs)
        os.close(reader)
        reader = None
        yield process
    finally:
        _close_writer(token)
        if reader is not None:
            os.close(reader)
        if process is not None:
            # Guardian only waits for its owned child after SIGKILL, never for
            # arbitrary descendants or model-server work. Keep the lease until
            # the guardian exits instead of killing it and dropping ownership.
            process.wait()


def _guardian(watch_fd, timeout, argv):
    # Signals sent to this helper request cleanup, never kill the helper before
    # it has signalled its owned worker group and reaped its direct child.
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    process = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(watch_fd, selectors.EVENT_READ)
            # The parent may have died before this helper was scheduled.
            if selector.select(0):
                return 125
            process = subprocess.Popen(argv, start_new_session=True, close_fds=True)
            deadline = time.monotonic() + timeout
            while True:
                # Observe exit without reaping: the zombie group leader keeps
                # its PID reserved until the final killpg and wait. A poll()
                # here could allow PID/group reuse before descendant cleanup.
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    return exited.si_status if exited.si_code == os.CLD_EXITED else -exited.si_status
                if stopping or time.monotonic() >= deadline or selector.select(.05):
                    return 125
    finally:
        if process is not None:
            # Also clear descendants after the direct executable exits. A child
            # retaining stdout must not escape simply because its parent ended.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        os.close(watch_fd)


if __name__ == '__main__':
    if len(sys.argv) < 5 or sys.argv[3] != '--':
        raise SystemExit('Internal guardian invocation is invalid')
    raise SystemExit(_guardian(int(sys.argv[1]), float(sys.argv[2]), sys.argv[4:]))
