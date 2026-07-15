"""
Tests for camoufox.server child-process cleanup (issue #172).

`launch_server()` used to call `process.wait()` with no signal/atexit
handling, so a Ctrl-C / SIGTERM to the Python process orphaned the Node
child (and its `/tmp/playwright-artifacts-*/profile-*` dir). These tests
exercise the extracted `_terminate()` helper directly against a real
subprocess, without needing the Node/Playwright server itself.

Run with:
    cd pythonlib && python -m pytest tests/test_server_cleanup.py -v
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.server import _terminate  # noqa: E402


def test_terminate_stops_a_running_process():
    process = subprocess.Popen(["sleep", "30"])
    assert process.poll() is None  # still running

    _terminate(process)

    assert process.poll() is not None  # reaped, no longer running


def test_terminate_is_a_noop_on_an_already_exited_process():
    process = subprocess.Popen(["true"])
    process.wait()
    assert process.poll() is not None

    # Should not raise even though the process already exited.
    _terminate(process)

    assert process.poll() is not None


def test_terminate_escalates_to_kill_if_process_ignores_terminate():
    # A process that traps SIGTERM so terminate() alone can't stop it,
    # forcing _terminate() to fall back to kill().
    process = subprocess.Popen(
        ["sh", "-c", "trap '' TERM; sleep 30"],
    )
    assert process.poll() is None

    _terminate(process)

    assert process.poll() is not None
