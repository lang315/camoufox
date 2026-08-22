"""
Regression test: a screen sampled for a scaled display must not be reported at dpr=1.

BrowserForge picks `screen.width`/`height` as CSS pixels *for a specific*
devicePixelRatio — macOS `960x540 @ dpr 2` describes a real 1920x1080 Retina panel.
`from_browserforge()`/`from_preset()` carry the dimensions across but drop the dpr
(there is no `window.devicePixelRatio` key in the emitted config), and headless
Firefox reports dpr=1 because there is no display. The page therefore sees
`960x540 @ dpr 1` — a size no device ships at 1x.

Systematic, not a quirk of one resolution. Fingerprints sampled for dpr != 1:

    macOS   169/200 (84%)
    linux    95/200 (48%)
    windows  74/200 (37%)

`960x540` is merely its most visible instance; `1728x1117 @ dpr1` is equally
not-a-real-1x-panel, just subtler.

Two fixes were considered and measured against the resolutions real scraped
fingerprints actually report at dpr~1 (observed data, not a hand-written table):

  - scaling the screen back to its physical panel (960x540@2 -> 1920x1080) scored
    only 3/8 -> 4/8, because it introduces the opposite implausibility: 3456x2234
    and 5120x2880 are Retina PHYSICAL panels that only ever run at 2x.
  - resampling from screens real devices report AT dpr~1, which is what shipped:
    correct by construction, and the bundled presets carry enough of them to keep
    diversity (macOS 13 distinct, windows 20, linux 11).

Not a split-brain: the getter and matchMedia agree at dpr=1. Forcing
`window.devicePixelRatio` to match is what causes that failure mode, and is
strictly worse — see build-tester/observer/probe_split.py.

Run with:
    cd camoufox && PYTHONPATH=pythonlib python3 -m pytest \
        pythonlib/tests/test_screen_dpr_coherence.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from camoufox.fingerprints import load_presets, resample_screen_for_dpr1  # noqa: E402


def real_dpr1_screens(preset_key):
    """Independently derived from the bundled presets, so membership assertions
    below are a real check rather than a restatement of the implementation."""
    presets = load_presets(152)["presets"]
    return {
        (s["width"], s["height"])
        for s in (p.get("screen", {}) for p in presets[preset_key])
        if s.get("width") and s.get("devicePixelRatio")
        and abs(s["devicePixelRatio"] - 1) < 0.02
    }


def _cfg(w=960, h=540):
    return {
        "screen.width": w, "screen.height": h,
        "screen.availWidth": w, "screen.availHeight": h - 25,
    }


# ---------------------------------------------------------------------------
# The resample
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("os_key,preset_key", [("mac", "macos"), ("win", "windows"), ("lin", "linux")])
def test_resampled_screen_is_one_real_devices_report_at_1x(os_key, preset_key):
    valid = real_dpr1_screens(preset_key)
    for _ in range(20):
        c = _cfg()
        resample_screen_for_dpr1(c, os_key, source_dpr=2, ff_version=152)
        assert (c["screen.width"], c["screen.height"]) in valid


def real_dpr1_blocks(preset_key):
    """Full (w, h, availW, availH) tuples, so avail can be checked as belonging to
    the SAME device as the screen rather than by a size heuristic."""
    presets = load_presets(152)["presets"]
    return {
        (s["width"], s["height"], s["availWidth"], s["availHeight"])
        for s in (p.get("screen", {}) for p in presets[preset_key])
        if s.get("width") and s.get("availWidth") and s.get("devicePixelRatio")
        and abs(s["devicePixelRatio"] - 1) < 0.02
    }


def test_avail_comes_from_the_same_real_screen():
    """avail must not be left over from the discarded screen, or the pair is a lie.

    Checked by whole-block membership, not by a delta heuristic: a real macOS
    menubar is ~25px, so "availHeight differs from height by 25" is indistinguishable
    from leftover data and cannot be used as the test.
    """
    valid = real_dpr1_blocks("macos")
    for _ in range(20):
        c = _cfg()
        resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
        block = (c["screen.width"], c["screen.height"],
                 c["screen.availWidth"], c["screen.availHeight"])
        assert block in valid, f"screen/avail are not one real device's pair: {block}"


def test_960x540_at_dpr1_never_survives():
    """The reported case: it must not come out the far side unchanged."""
    for _ in range(30):
        c = _cfg(960, 540)
        resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
        assert (c["screen.width"], c["screen.height"]) != (960, 540)


def test_keeps_diversity():
    """Collapsing every headless run to one screen would trade one tell for another."""
    seen = set()
    for _ in range(40):
        c = _cfg()
        resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
        seen.add((c["screen.width"], c["screen.height"]))
    assert len(seen) >= 3, f"resampling is near-constant: {seen}"


# ---------------------------------------------------------------------------
# No-ops
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dpr", [1, 1.0, None, 0])
def test_noop_when_dpr_already_one_or_unknown(dpr):
    c = _cfg(1920, 1080)
    before = dict(c)
    resample_screen_for_dpr1(c, "mac", source_dpr=dpr, ff_version=152)
    assert c == before


def test_noop_when_screen_absent():
    """A config the caller drives itself must be left completely alone."""
    c = {"navigator.platform": "MacIntel"}
    before = dict(c)
    resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
    assert c == before


# ---------------------------------------------------------------------------
# Wiring: the resample must reach the generated config
# ---------------------------------------------------------------------------


def _binary():
    for c in (os.environ.get("CFX_BIN"),
              "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"):
        if c and os.path.exists(c):
            return c
    return None


@pytest.mark.skipif(_binary() is None, reason="needs a Camoufox binary (set CFX_BIN)")
def test_headless_macos_screens_are_all_real_1x_resolutions():
    import json

    from camoufox.utils import launch_options

    valid = real_dpr1_screens("macos")
    drawn = []
    for _ in range(12):
        lo = launch_options(headless=True, os="macos", ff_version=152,
                            i_know_what_im_doing=True, executable_path=_binary())
        env = lo["env"]
        cfg = json.loads("".join(
            env[k] for k in sorted(
                (k for k in env if k.startswith("CAMOU_CONFIG_")),
                key=lambda k: int(k.rsplit("_", 1)[1]),
            )
        ))
        drawn.append((cfg.get("screen.width"), cfg.get("screen.height")))

    bad = [d for d in drawn if d not in valid]
    assert not bad, f"screens no real device reports at 1x reached the config: {bad}"
    assert len(set(drawn)) >= 3, f"headless macOS collapsed to {set(drawn)}"
