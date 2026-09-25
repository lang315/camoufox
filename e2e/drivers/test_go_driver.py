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


def test_a_reply_outside_the_host_codepage_reaches_the_caller(monkeypatch, tmp_path):
    # U+201D encodes as e2 80 9d; 0x9d is undefined in cp1252, which killed the reader
    # thread on Windows and turned every later call into a timeout (e2e run 36109758649).
    # Only a host whose locale encoding is cp1252 can see this go red.
    echo = tmp_path / "echo.py"
    echo.write_text("import sys, json\nreq = json.loads(sys.stdin.readline())\n"
                    "sys.stdout.buffer.write(json.dumps({'id': req['id'], 'result': '\\u201d'}, ensure_ascii=False).encode() + b'\\n')\n"
                    "sys.stdout.flush()\n")
    monkeypatch.setattr(go, "RPC_TIMEOUT_S", 10)
    real_popen = go.subprocess.Popen
    monkeypatch.setattr(go.subprocess, "Popen", lambda argv, **kw: real_popen([sys.executable, str(echo)], **kw))
    monkeypatch.setattr(go, "build", lambda: echo)
    assert go.GoDriver(tmp_path).rpc("page.eval", "p1", js="1") == "\u201d"
