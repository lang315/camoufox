"""stock-gpu-parity.stop_browser returns only when every process of the browser is gone (#452).

On Windows a child that outlived `taskkill /T` still held the log the parent's
stdout was pointed at, so the guard's unlink failed with WinError 32. The kill
command is replaced by a no-op here, so a helper that relies on it for the
children (the old one) returns with them alive on any OS.
"""

import importlib.util
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import psutil
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "browser/tests/playwright/patches/stock-gpu-parity.py"

# The child sleeps; the parent prints its pid and either waits (a live tree) or exits (an orphan).
PARENT = textwrap.dedent("""
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[1]])
    print(child.pid, flush=True)
    if sys.argv[2] == "wait":
        time.sleep(600)
""")


@pytest.fixture(scope="module")
def guard():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("stock_gpu_parity", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def profile():
    with tempfile.TemporaryDirectory(prefix="stop-browser-") as path:
        yield path


@pytest.mark.parametrize("parent_state", ["wait", "exit"])
def test_no_process_of_the_browser_is_alive_when_stop_browser_returns(guard, profile, monkeypatch, parent_state):
    proc = subprocess.Popen([sys.executable, "-c", PARENT, profile, parent_state], stdout=subprocess.PIPE, text=True)
    # The kill command gives no guarantee about the children; only waiting on them does.
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **k: proc.kill())
    child = psutil.Process(int(proc.stdout.readline()))
    try:
        guard.stop_browser(proc, profile)
        assert not child.is_running(), f"child {child.pid} outlived stop_browser"
    finally:
        proc.stdout.close()
        if child.is_running():
            child.kill()
        proc.kill()
        proc.wait()
