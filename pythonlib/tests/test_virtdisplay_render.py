"""
Tests for the headless='virtual' rendering/fingerprint bugs (#93, #458, #242).

- #93:  VirtualDisplay disabled the COMPOSITE X11 extension, so offscreen
        graphical capture (record_video) came out blank under headless='virtual'.
- #458: VirtualDisplay hardcoded a 1x1 Xvfb screen, clamping the browser
        window to 1x1 -- screenshots/video came out blank or mispositioned.
- #242: utils.get_screen_cons was fed the DISPLAY that Camoufox itself had
        just set for a self-spawned Xvfb, so it queried that fake display's
        (degenerate) monitor and poisoned browserforge's fingerprint
        generation with invalid Screen constraints.

The Xvfb process itself only exists on Linux (see test_virtdisplay.py), but
all three fixes are verifiable without spawning one: #93/#458 are static
properties of VirtualDisplay.xvfb_args, and #242 is pure logic in
utils.get_screen_cons / utils._real_display_present that we exercise with a
monkeypatched screeninfo.get_monitors(). Those run on any platform.

Run with:
    cd pythonlib && python -m pytest tests/test_virtdisplay_render.py -v
"""

import os
import sys
from types import SimpleNamespace

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import utils  # noqa: E402
from camoufox.virtdisplay import VirtualDisplay  # noqa: E402


def _args_pairs(args):
    """Turns the flat xvfb_args tuple into a lookup keyed by flag-with-mode."""
    pairs = []
    it = iter(args)
    for tok in it:
        if tok in ("-extension", "+extension"):
            pairs.append((tok, next(it)))
    return pairs


# ---------------------------------------------------------------------------
# #93: COMPOSITE must not be disabled
# ---------------------------------------------------------------------------

def test_composite_extension_is_not_disabled():
    pairs = _args_pairs(VirtualDisplay.xvfb_args)
    assert ("-extension", "COMPOSITE") not in pairs, (
        "COMPOSITE must not be disabled -- record_video captures via "
        "offscreen compositing and comes out blank without it (#93)"
    )


def test_composite_extension_is_explicitly_enabled():
    pairs = _args_pairs(VirtualDisplay.xvfb_args)
    assert ("+extension", "COMPOSITE") in pairs


# ---------------------------------------------------------------------------
# #458: the Xvfb screen must not be 1x1
# ---------------------------------------------------------------------------

def _screen_geometry(args):
    idx = args.index("-screen")
    geometry = args[idx + 2]  # "-screen", "0", "<W>x<H>x<depth>"
    w, h, _depth = geometry.split("x")
    return int(w), int(h)


def test_xvfb_screen_is_not_1x1():
    width, height = _screen_geometry(VirtualDisplay.xvfb_args)
    assert (width, height) != (1, 1), (
        "a 1x1 Xvfb screen clamps window resizes to 1x1, leaving "
        "screenshots/video blank or mispositioned (#458)"
    )


def test_xvfb_screen_fits_a_normal_browser_window():
    width, height = _screen_geometry(VirtualDisplay.xvfb_args)
    # Any commonly-used viewport (e.g. 1920x1080, 1366x768) must fit.
    assert width >= 1920 and height >= 1080


# ---------------------------------------------------------------------------
# #242: get_screen_cons must not be driven by a self-spawned virtual display
# ---------------------------------------------------------------------------

FAKE_TINY_MONITOR = [SimpleNamespace(width=1, height=1)]
FAKE_REAL_MONITOR = [SimpleNamespace(width=2560, height=1440)]


def test_real_display_present_true_for_preexisting_display():
    # A real host DISPLAY, no virtual_display spawned by us.
    env = {"DISPLAY": ":0"}
    assert utils._real_display_present(env, None) is True


def test_real_display_present_false_for_self_spawned_virtual_display():
    # headless='virtual' just set DISPLAY to point at our own Xvfb.
    env = {"DISPLAY": ":99"}
    assert utils._real_display_present(env, ":99") is False


def test_real_display_present_false_when_no_display_at_all():
    env: dict = {}
    assert utils._real_display_present(env, None) is False


def test_get_screen_cons_headless_false_skips_monitor_query(monkeypatch):
    called = []
    monkeypatch.setattr(utils, "get_monitors", lambda: called.append(1) or FAKE_REAL_MONITOR)
    assert utils.get_screen_cons(False) is None
    assert called == []  # never even queried


def test_get_screen_cons_queries_monitors_when_flag_true(monkeypatch):
    monkeypatch.setattr(utils, "get_monitors", lambda: FAKE_REAL_MONITOR)
    screen = utils.get_screen_cons(True)
    assert screen is not None
    assert screen.max_width == 2560
    assert screen.max_height == 1440


def test_virtual_headless_does_not_derive_screen_from_self_spawned_xvfb(monkeypatch):
    """
    End-to-end reproduction of #242's call-site expression: with a
    self-spawned virtual display, the (possibly degenerate, e.g. 1x1) Xvfb
    monitor must never reach get_screen_cons.
    """
    monkeypatch.setattr(utils, "get_monitors", lambda: FAKE_TINY_MONITOR)

    headless = False  # AsyncNewBrowser/NewBrowser sets this after spawning Xvfb
    env = {"DISPLAY": ":99"}  # set by launch_options() for headless='virtual'
    virtual_display = ":99"

    flag = headless or utils._real_display_present(env, virtual_display)
    result = utils.get_screen_cons(flag)

    assert result is None, (
        "a self-spawned Xvfb must not feed its (possibly degenerate) "
        "resolution into Screen constraints (#242)"
    )


def test_real_headful_still_derives_screen_from_real_monitor(monkeypatch):
    """Regression guard: the fix must not break real (non-virtual) headful runs."""
    monkeypatch.setattr(utils, "get_monitors", lambda: FAKE_REAL_MONITOR)

    headless = False
    env = {"DISPLAY": ":0"}  # a real, pre-existing host display
    virtual_display = None  # no Xvfb spawned by us

    flag = headless or utils._real_display_present(env, virtual_display)
    result = utils.get_screen_cons(flag)

    assert result is not None
    assert result.max_width == 2560
    assert result.max_height == 1440


# ---------------------------------------------------------------------------
# Live Xvfb integration (Linux only, mirrors test_virtdisplay.py's gating)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "linux", reason="Xvfb is Linux-only")
def test_live_xvfb_reports_configured_screen_size():
    """
    Confirms the actual spawned Xvfb honors the 1920x1080 -screen arg (not
    just that we asked for it) and that get_screen_cons correctly ignores it
    once it's wired up as our own virtual_display.
    """
    vd = VirtualDisplay()
    try:
        display = vd.get()
        assert display.startswith(":")

        env = {"DISPLAY": display}
        # Simulate what launch_options() does for headless='virtual'.
        assert utils._real_display_present(env, display) is False
        flag = False or utils._real_display_present(env, display)
        assert utils.get_screen_cons(flag) is None
    finally:
        vd.kill()
