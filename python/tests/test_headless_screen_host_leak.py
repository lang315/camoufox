"""
Regression test: in headless mode the fingerprint's Screen constraint must not
be derived from the HOST monitor.

launch_options() passed `get_screen_cons(headless or _real_display_present(...))`,
so running headless fed browserforge a Screen capped at whatever monitor the
machine happened to have. That constraint exists for one reason -- to keep the
browser WINDOW fitting the display it will be shown on -- and headless has no
display at all.

Measured damage on a 1512x982 host (a MacBook Pro 14"), generating firefox+macOS:
  - the output collapsed to two values, 960x540 and 1512x982
  - 960x540 is a size no real Mac reports, so the spoofed profile was itself a tell
  - 1512x982 is the HOST's own resolution, i.e. the fingerprint correlated with
    the machine doing the scraping
  - results became machine-dependent: the same code on a different host samples a
    different space, so any recorded measurement is unreproducible

This is the same class of bug as #242, which established that a self-spawned Xvfb
is not a real monitor and must not drive Screen constraints. Headless is the
remaining case: no display exists, so nothing should be derived from the host.

Run with:
    cd camoufox && PYTHONPATH=pythonlib python3 -m pytest \
        pythonlib/tests/test_headless_screen_host_leak.py -v
"""
import os
import sys
from types import SimpleNamespace

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from camoufox import display, utils  # noqa: E402

# largest_display() returns one DisplaySize (CSS pixels), not a monitor list.
FAKE_HOST_MONITOR = SimpleNamespace(width=1512, height=982)


# ---------------------------------------------------------------------------
# The policy, as get_screen_cons() states it: only a headful launch asks the host
# monitor; headless never queries it.
# ---------------------------------------------------------------------------


def test_headless_never_queries_the_host_monitor(monkeypatch):
    queried = []
    monkeypatch.setattr(
        utils, "largest_display", lambda: queried.append(1) or FAKE_HOST_MONITOR
    )
    assert utils.get_screen_cons(True) is None
    assert queried == [], "headless must not read the host monitor at all"


def test_headful_real_display_still_constrains(monkeypatch):
    """Guard against over-correcting: the headful path must keep its constraint."""
    monkeypatch.setattr(utils, "largest_display", lambda: FAKE_HOST_MONITOR)

    screen = utils.get_screen_cons(False)
    assert screen is not None
    assert screen.max_width == 1512
    assert screen.max_height == 982


def test_headful_on_a_self_spawned_xvfb_does_not_query_the_monitor(monkeypatch):
    """#242 stays fixed at the call site: launch_options must not bound the
    identity by our own Xvfb."""
    monkeypatch.setattr(utils, "has_display", lambda env: True)
    monkeypatch.setattr(
        utils, "largest_display", lambda: pytest.fail("queried a self-spawned Xvfb")
    )
    utils.launch_options(
        headless=False, os="linux", virtual_display=":99", i_know_what_im_doing=True
    )


# ---------------------------------------------------------------------------
# Wiring: the tests above all pin the HELPER. Reverting the launch_options call
# site alone would leave every one of them passing, so this asserts the absence
# of the leak in the actual generated config rather than a helper's return value.
# ---------------------------------------------------------------------------

# A resolution no fingerprint dataset contains, so any appearance in the output
# can only have come from the monitor probe.
SENTINEL_MONITOR = SimpleNamespace(width=1234, height=567)


def _camou_config(launch_opts):
    """Reassemble the chunked CAMOU_CONFIG_<n> env vars launch_options emits."""
    import json

    env = launch_opts["env"]
    parts = [env[k] for k in sorted(
        (k for k in env if k.startswith("CAMOU_CONFIG_")),
        key=lambda k: int(k.rsplit("_", 1)[1]),
    )]
    return json.loads("".join(parts))


def test_launch_options_headless_output_never_contains_host_resolution(monkeypatch):
    """The leak must be absent from the config that actually reaches the browser."""
    from camoufox.utils import launch_options

    monkeypatch.setattr(utils, "largest_display", lambda: SENTINEL_MONITOR)

    drawn = []
    for _ in range(8):  # generation is random; a single draw proves little
        cfg = _camou_config(
            launch_options(
                headless=True, os="macos", ff_version=152,
                i_know_what_im_doing=True,
            )
        )
        drawn.append((cfg.get("screen.width"), cfg.get("screen.height")))

    assert (1234, 567) not in drawn, (
        f"the host monitor reached the generated fingerprint ({drawn}) -- the "
        "launch_options call site no longer skips get_screen_cons for headless"
    )
    # Not "every draw exceeds the bound": unconstrained macOS legitimately includes
    # 960x540 (~5% of browserforge's firefox+macOS data). Constrained, NOTHING can
    # exceed the monitor, so one draw over it is sufficient and non-flaky.
    assert max(w for w, _ in drawn) > 1234, (
        f"no draw exceeded the fake host monitor's 1234px bound ({drawn}), so "
        "generation is still being constrained by it"
    )
