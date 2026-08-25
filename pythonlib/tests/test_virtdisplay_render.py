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
utils.get_screen_cons / utils._real_display_present that we exercise with a
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
# So the defaults are upstream's again, and what is worth pinning here is that
# the escape hatches still work -- a caller who does want a real framebuffer to
# draw into must be able to ask for one.
# ---------------------------------------------------------------------------

def _screen_geometry(args):
    idx = args.index("-screen")
    geometry = args[idx + 2]  # "-screen", "0", "<W>x<H>x<depth>"
    w, h, _depth = geometry.split("x")
    return int(w), int(h)


def test_composite_is_off_by_default_and_can_be_enabled(monkeypatch):
    monkeypatch.delenv("CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE", raising=False)
    assert ("-extension", "COMPOSITE") in _args_pairs(VirtualDisplay().xvfb_args)

    monkeypatch.setenv("CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE", "1")
    assert ("+extension", "COMPOSITE") in _args_pairs(VirtualDisplay().xvfb_args)


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


def test_real_display_present_true_for_preexisting_display():
    # A real host DISPLAY, no virtual_display spawned by us.
    env = {"DISPLAY": ":0"}
    assert utils._real_display_present(env, None) is True


def test_real_display_present_false_for_self_spawned_virtual_display():
    # headless='virtual' just set DISPLAY to point at our own Xvfb.
    env = {"DISPLAY": ":99"}
    assert utils._real_display_present(env, ":99") is False


def test_real_display_present_false_on_linux_when_no_display_at_all(monkeypatch):
    # DISPLAY / WAYLAND_DISPLAY only exist on Linux, so an empty env means "no
    # session" there and nothing at all anywhere else -- hence the OS pin.
    monkeypatch.setattr(display, "OS_NAME", "lin")
    env: dict = {}
    assert utils._real_display_present(env, None) is False


def test_real_display_present_true_off_linux_without_display(monkeypatch):
    # Windows and macOS always have a desktop session; keying off DISPLAY alone
    # skipped the screen constraint entirely on those platforms.
    monkeypatch.setattr(display, "OS_NAME", "mac")
    assert utils._real_display_present({}, None) is True


def test_get_screen_cons_headless_false_skips_monitor_query(monkeypatch):
    called = []
    monkeypatch.setattr(utils, "largest_display", lambda: called.append(1) or FAKE_REAL_MONITOR)
    assert utils.get_screen_cons(False) is None
    assert called == []  # never even queried


def test_get_screen_cons_queries_monitors_when_flag_true(monkeypatch):
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_REAL_MONITOR)
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
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_TINY_MONITOR)

    headless = False  # AsyncNewBrowser/NewBrowser sets this after spawning Xvfb
    env = {"DISPLAY": ":99"}  # set by launch_options() for headless='virtual'
    virtual_display = ":99"

    flag = utils._should_constrain_to_host_display(headless, env, virtual_display)
    result = utils.get_screen_cons(flag)

    assert result is None, (
        "a self-spawned Xvfb must not feed its (possibly degenerate) "
        "resolution into Screen constraints (#242)"
    )


def test_real_headful_still_derives_screen_from_real_monitor(monkeypatch):
    """Regression guard: the fix must not break real (non-virtual) headful runs."""
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_REAL_MONITOR)

    headless = False
    env = {"DISPLAY": ":0"}  # a real, pre-existing host display
    virtual_display = None  # no Xvfb spawned by us

    flag = utils._should_constrain_to_host_display(headless, env, virtual_display)
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
        flag = utils._should_constrain_to_host_display(False, env, display)
        assert utils.get_screen_cons(flag) is None
    finally:
        vd.kill()
