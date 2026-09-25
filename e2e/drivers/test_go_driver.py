"""The goapi driver fails a wedged call instead of hanging the whole run.

On Windows, pytest-timeout can only use its thread method, which kills the
whole process, so a hung RPC used to erase the run's summary (e2e run
36091364856).
"""

import sys
import time

import pytest

from drivers import go


def test_a_driver_that_never_answers_times_out(monkeypatch, tmp_path):
    silent = tmp_path / "silent.py"
    silent.write_text("import sys, time\nsys.stdin.readline()\ntime.sleep(60)\n")
    monkeypatch.setattr(go, "RPC_TIMEOUT_S", 1)
    real_popen = go.subprocess.Popen
    monkeypatch.setattr(go.subprocess, "Popen", lambda argv, **kw: real_popen([sys.executable, str(silent)], **kw))
    monkeypatch.setattr(go, "build", lambda: silent)
    d = go.GoDriver(tmp_path)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="no reply in 1s"):
        d.rpc("page.eval", "p1", js="1")
    assert time.monotonic() - t0 < 10
    assert d.proc is None, "the wedged driver was killed and forgotten, so the next call starts a fresh one"
