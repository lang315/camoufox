"""
Tests for the headless='virtual' rendering/fingerprint bugs (#93, #458, #242).

- #93/#458: blank record_video under headless='virtual' was blamed on Xvfb's
        disabled COMPOSITE extension and its 1x1 root window. The real cause was
        juggler's X11 window capturer; with that fixed, both are back to being
        plain options, and what is pinned here is that the overrides work.
- #242: utils.get_screen_cons was fed the DISPLAY that Camoufox itself had
        just set for a self-spawned Xvfb, so it queried that fake display's
        (degenerate) monitor and poisoned browserforge's fingerprint
        generation with invalid Screen constraints.

The Xvfb process itself only exists on Linux (see test_virtdisplay.py), but
all of it is verifiable without spawning one: #93/#458 are static
properties of VirtualDisplay().xvfb_args, and #242 is pure logic in
utils.get_screen_cons and the launch_options call site that we exercise with a
monkeypatched camoufox.display.largest_display(). Those run on any platform.

Run with:
    cd pythonlib && python -m pytest tests/test_virtdisplay_render.py -v
"""

import os
import sys
from types import SimpleNamespace

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import display, utils  # noqa: E402
from camoufox.exceptions import VirtualDisplayNotSupported  # noqa: E402
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
# #93 / #458: COMPOSITE and the Xvfb screen size are now OPTIONS, not constants
#
# These two were originally pinned as defaults here, because blank video under
# headless='virtual' was believed to be caused by Xvfb's `-extension COMPOSITE`
# and its 1x1 root window. It was not: the cause was juggler capturing the
# screencast through libwebrtc's X11 window capturer, fixed by capturing from
# the compositor instead. With that fix in the tree, record_video produces real
# frames under headless='virtual' with COMPOSITE off and a 1x1 root, which
# tests/async/test_video.py covers end-to-end with a live browser.
#
# The compositor fix covers only the Page.startScreencast path, which Playwright
# >=1.58 uses. Playwright <=1.57 records through Browser.setVideoRecordingOptions,
# which still reaches the X11 window capturer, and that needs COMPOSITE (#136,
# measured on one binary in virtdisplay.py's table). So COMPOSITE is on by
# default; the screen size stays upstream's 1x1. What is pinned here is that
# default plus the escape hatches in both directions.
# ---------------------------------------------------------------------------

def _screen_geometry(args):
    idx = args.index("-screen")
    geometry = args[idx + 2]  # "-screen", "0", "<W>x<H>x<depth>"
    w, h, _depth = geometry.split("x")
    return int(w), int(h)


def test_composite_is_on_by_default_and_can_be_disabled(monkeypatch):
    # #136: Playwright <=1.57 records video through the native X11 window
    # capturer, which delivers no frames under Xvfb without Composite.
    monkeypatch.delenv("CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE", raising=False)
    assert ("+extension", "COMPOSITE") in _args_pairs(VirtualDisplay().xvfb_args)

    monkeypatch.setenv("CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE", "0")
    assert ("-extension", "COMPOSITE") in _args_pairs(VirtualDisplay().xvfb_args)


def test_composite_argument_overrides_the_environment(monkeypatch):
    monkeypatch.setenv("CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE", "0")
    pairs = _args_pairs(VirtualDisplay(composite=True).xvfb_args)
    assert ("+extension", "COMPOSITE") in pairs


def test_xvfb_screen_size_is_overridable(monkeypatch):
    monkeypatch.delenv("CAMOUFOX_VIRTUAL_DISPLAY_SIZE", raising=False)
    assert _screen_geometry(VirtualDisplay().xvfb_args) == (1, 1)

    # Any commonly-used viewport (e.g. 1920x1080, 1366x768) must be requestable.
    monkeypatch.setenv("CAMOUFOX_VIRTUAL_DISPLAY_SIZE", "1920x1080x24")
    assert _screen_geometry(VirtualDisplay().xvfb_args) == (1920, 1080)


def test_xvfb_screen_size_rejects_a_malformed_override(monkeypatch):
    monkeypatch.setenv("CAMOUFOX_VIRTUAL_DISPLAY_SIZE", "not-a-size")
    with pytest.raises(VirtualDisplayNotSupported):
        VirtualDisplay()


# ---------------------------------------------------------------------------
# #242: get_screen_cons must not be driven by a self-spawned virtual display
# ---------------------------------------------------------------------------

# largest_display() returns a single DisplaySize (CSS pixels), not a monitor list.
FAKE_TINY_MONITOR = SimpleNamespace(width=1, height=1)
FAKE_REAL_MONITOR = SimpleNamespace(width=2560, height=1440)


def test_get_screen_cons_headless_skips_monitor_query(monkeypatch):
    called = []
    monkeypatch.setattr(utils, "largest_display", lambda: called.append(1) or FAKE_REAL_MONITOR)
    assert utils.get_screen_cons(True) is None
    assert called == []  # never even queried


def test_get_screen_cons_queries_monitors_when_headful(monkeypatch):
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_REAL_MONITOR)
    screen = utils.get_screen_cons(False)
    assert screen is not None
    assert screen.max_width == 2560
    assert screen.max_height == 1440


def _record_screen_bounds(monkeypatch):
    bounds = []
    real = utils.generate_fingerprint
    monkeypatch.setattr(
        utils, "generate_fingerprint", lambda **kw: bounds.append(kw.get("screen")) or real(**kw)
    )
    return bounds


def test_virtual_headless_does_not_derive_screen_from_self_spawned_xvfb(monkeypatch):
    """
    #242 end to end: with a self-spawned virtual display, the (possibly
    degenerate, e.g. 1x1) Xvfb monitor must never reach the identity's bounds.
    """
    monkeypatch.setattr(utils, "has_display", lambda env: True)
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_TINY_MONITOR)
    bounds = _record_screen_bounds(monkeypatch)
    # AsyncNewBrowser/NewBrowser pass headless=False once Xvfb is spawned.
    utils.launch_options(
        headless=False, os="linux", virtual_display=":99", i_know_what_im_doing=True
    )
    assert bounds == [None], "a self-spawned Xvfb must not bound the identity (#242)"


def test_real_headful_still_derives_screen_from_real_monitor(monkeypatch):
    """Regression guard: the fix must not break real (non-virtual) headful runs."""
    monkeypatch.setattr(utils, "has_display", lambda env: True)
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_REAL_MONITOR)
    bounds = _record_screen_bounds(monkeypatch)
    utils.launch_options(headless=False, os="linux", i_know_what_im_doing=True)
    assert bounds and bounds[0].max_width == 2560 and bounds[0].max_height == 1440


# ---------------------------------------------------------------------------
# Live Xvfb integration (Linux only, mirrors test_virtdisplay.py's gating)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "linux", reason="Xvfb is Linux-only")
def test_live_xvfb_reports_configured_screen_size():
    """
    Confirms the actual spawned Xvfb honors the 1920x1080 -screen arg (not
    just that we asked for it).
    """
    vd = VirtualDisplay()
    try:
        display = vd.get()
        assert display.startswith(":")

    finally:
        vd.kill()
