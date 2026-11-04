"""getter-cost-parity.py: its verdict (what it calls slower, faster and equal) and what a silent stock launch reports.

The negative controls for #359: a getter three times its control's cost against
stock's one times fails, a build that is uniformly slower does not, and a getter
that skips stock's work still fails the other way. The #384 tests run `stock_launch`
against a stand-in for stock Firefox that exits, hangs or reports.
"""

import importlib.util
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "browser/tests/playwright/patches/getter-cost-parity.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("getter_cost_parity", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_getter_three_times_its_control_against_stock_at_one_times_is_slower(guard):
    # stock: getter 60 ns, control 40 ns. Camoufox: control 40 ns, getter 180 ns.
    assert guard.verdict(60, 180, 40, 40) == (True, False)


def test_a_uniformly_slower_build_is_not_slower(guard):
    # Every getter, control included, costs 2.2x: 132 against 60 is 2.2x raw and 72 ns apart.
    assert guard.verdict(60, 132, 40, 88) == (False, False)


def test_equal_costs_pass(guard):
    assert guard.verdict(60, 60, 40, 40) == (False, False)


def test_a_large_ratio_under_the_gap_is_not_slower(guard):
    assert guard.verdict(8, 24, 40, 40) == (False, False)


def test_a_getter_that_returns_early_is_still_faster(guard):
    # stock: 107 ns against a 50 ns control. Camoufox: 20 ns against a 60 ns control.
    assert guard.verdict(107, 20, 50, 60) == (False, True)


def test_the_median_ignores_one_noisy_launch(guard):
    def run(v):
        return {"first": {"x": 1.0}, "window": {"g": v}, "worker": {}}
    summary = guard.summarise([run(50), run(52), run(51), run(300), run(49), run(50)])
    assert summary["window"]["g"] == 50.5


def test_exactly_twice_stock_is_not_slower_but_over_it_by_the_gap_is(guard):
    # SLOWER_FACTOR is a strict ">": 60 against 30 is 2.0x with a 30 ns gap.
    assert guard.verdict(30, 60, 40, 40) == (False, False)
    assert guard.verdict(30, 60.1, 40, 40) == (True, False)


def test_exactly_the_gap_is_slower_and_just_under_it_is_not(guard):
    # MIN_GAP_NS is ">=": 50 against 20 is 2.5x and exactly 30 ns apart.
    assert guard.verdict(20, 50, 40, 40) == (True, False)
    assert guard.verdict(20, 49.9, 40, 40) == (False, False)


def test_faster_needs_the_gap_and_a_strictly_smaller_ratio(guard):
    # 30 ns cheaper against a control that is 5x dearer here: faster.
    assert guard.verdict(100, 70, 40, 200) == (False, True)
    assert guard.verdict(100, 70.5, 40, 200) == (False, False)
    # Same ratio to the control on both sides: not faster, however large the gap.
    assert guard.verdict(100, 50, 40, 40) == (False, False)


def fake_stock(tmp_path, body):
    """An executable that stands in for stock Firefox: `body` runs with the page URL as `url`."""
    script = tmp_path / "fake-firefox"
    script.write_text(f"#!{sys.executable}\nimport sys\nurl = sys.argv[-1]\n{body}\n")
    script.chmod(0o755)
    return script


@pytest.fixture
def server(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(guard, "stop_stock", lambda profile, proc: (proc.kill(), proc.wait(), shutil.rmtree(profile)))
    srv = guard.Server(("127.0.0.1", 0), guard.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def test_a_stock_launch_that_exits_without_reporting_shows_its_status_and_output(guard, server, tmp_path, capsys):
    binary = fake_stock(tmp_path, "print('crashed: boom', flush=True); sys.exit(3)")
    result, why = guard.stock_launch(binary, "http://127.0.0.1/", server, timeout=2)
    assert result is None and why == "exit status 3"
    assert "crashed: boom" in capsys.readouterr().out


def test_a_stock_launch_that_hangs_says_it_is_still_running(guard, server, tmp_path, capsys):
    binary = fake_stock(tmp_path, "import time; print('started', flush=True); time.sleep(60)")
    result, why = guard.stock_launch(binary, "http://127.0.0.1/", server, timeout=2)
    assert result is None and why == "still running"
    assert "started" in capsys.readouterr().out


def test_a_stock_launch_that_reports_returns_its_result_and_leaves_nothing_behind(guard, server, tmp_path, capsys):
    port = server.server_address[1]
    binary = fake_stock(
        tmp_path,
        f"import urllib.request\nurllib.request.urlopen(urllib.request.Request("
        f"'http://127.0.0.1:{port}/result', data=b'{{\"ok\": 1}}'))",
    )
    result, why = guard.stock_launch(binary, "http://127.0.0.1/", server, timeout=30)
    assert (result, why) == ({"ok": 1}, "")
    assert capsys.readouterr().out == ""
    assert not list(tmp_path.glob("getter-cost-parity-*"))
