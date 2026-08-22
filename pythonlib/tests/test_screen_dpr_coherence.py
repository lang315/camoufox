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
    """avail must not be left over from the discarded screen.

    Checked by whole-block membership, not by a delta heuristic: a real macOS
    menubar is ~25px, so "availHeight differs from height by 25" is indistinguishable
    from leftover data and cannot be used as the test.

    Scope note: verbatim block membership holds only when the config carries no
    screen.availTop, as here. With one present, availHeight is deliberately shrunk to
    fit the real menu bar (see test_macos_availtop_is_a_plausible_menu_bar), so the
    block is no longer byte-identical to a scraped device. Do not "fix" the code to
    satisfy a stricter reading of this test.
    """
    valid = real_dpr1_blocks("macos")
    for _ in range(20):
        c = _cfg()
        resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
        block = (c["screen.width"], c["screen.height"],
                 c["screen.availWidth"], c["screen.availHeight"])
        assert block in valid, f"screen/avail are not one real device's pair: {block}"


def test_pool_keeps_duplicates_so_sampling_tracks_real_prevalence():
    """The pool is a LIST with duplicates, so choice() weights by how often a
    resolution actually occurs. A future set()/dict.fromkeys() 'cleanup' would
    silently turn this into a uniform draw over distinct values and nothing else
    would fail, so it is locked here."""
    from camoufox.fingerprints import _real_dpr1_screens

    pool = _real_dpr1_screens("mac", 152)
    distinct = {(s["width"], s["height"]) for s in pool}
    assert len(pool) > len(distinct), (
        "pool was deduplicated: sampling is now uniform over distinct resolutions "
        "instead of weighted by real prevalence"
    )


def test_macos_availtop_is_a_plausible_menu_bar():
    """Removing the availTop impossibility must not replace it with an implausible
    value: macOS always reserves a menu bar, and it is tens of pixels, not hundreds."""
    from camoufox.fingerprints import FP_GENERATOR, from_browserforge

    seen = 0
    for _ in range(60):
        fp = FP_GENERATOR.generate(os="macos")
        dpr = fp.screen.devicePixelRatio
        if not dpr or abs(dpr - 1) < 0.02:
            continue
        cfg = from_browserforge(fp, "152")
        if "screen.availTop" not in cfg:
            continue
        resample_screen_for_dpr1(cfg, "mac", dpr, 152)
        top = cfg["screen.availTop"]
        seen += 1
        assert 0 < top <= 60, f"availTop={top} is not a macOS menu bar"
        assert top + cfg["screen.availHeight"] <= cfg["screen.height"]
    assert seen, "no scaled-display macOS fingerprints were exercised"


def test_macos_never_reports_a_zero_menu_bar():
    """macOS always reserves a menu bar, so availTop=0 with availHeight < height is
    not a real Mac. BrowserForge never emits 0 today, so this branch is unreachable
    from the default path -- but it is a stated guarantee, and the two other
    unreachable-but-stated guarantees in this file both survived mutation testing
    until they were pinned here."""
    c = _cfg()
    c["screen.availTop"] = 0
    resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
    assert c["screen.availTop"] > 0
    assert c["screen.availTop"] + c["screen.availHeight"] <= c["screen.height"]


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
# Degradation and caching. Both of these survived mutation testing in review:
# deleting the empty-pool guard, and dropping the presets file from the cache key,
# each left the suite green while breaking a documented guarantee.
# ---------------------------------------------------------------------------


def test_noop_when_the_bundle_has_no_dpr1_screens():
    """Pre-v150 presets carry no dpr~1 entries for any OS, so this must degrade to a
    clean no-op. Without the guard it is IndexError from choice([]) at launch time."""
    c = _cfg()
    before = dict(c)
    resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=140)
    assert c == before


def test_empty_pool_for_one_version_does_not_poison_another():
    """The cache is keyed on the resolved presets FILE for exactly this reason."""
    resample_screen_for_dpr1(_cfg(), "mac", source_dpr=2, ff_version=140)  # empty pool
    valid = real_dpr1_screens("macos")
    c = _cfg()
    resample_screen_for_dpr1(c, "mac", source_dpr=2, ff_version=152)
    assert (c["screen.width"], c["screen.height"]) in valid


# ---------------------------------------------------------------------------
# Composition. Every test above drives a hand-built 4-key dict; that is what let a
# real availTop incoherence through review. These run the resample over a genuine
# from_browserforge config, alongside the fixups that follow it in launch_options.
# ---------------------------------------------------------------------------


def test_avail_offsets_do_not_survive_the_swapped_screen():
    """availTop/availLeft are not in the preset block, so a naive swap leaves them
    pointing at the discarded device: availTop + availHeight > screen.height."""
    from camoufox.fingerprints import (FP_GENERATOR, clamp_window_dimensions,
                                       fix_screen_no_taskbar, from_browserforge)

    for _ in range(40):
        fp = FP_GENERATOR.generate(os="macos")
        dpr = fp.screen.devicePixelRatio
        if not dpr or abs(dpr - 1) < 0.02:
            continue
        cfg = from_browserforge(fp, "152")
        resample_screen_for_dpr1(cfg, "mac", dpr, 152)
        fix_screen_no_taskbar(cfg, "mac")
        clamp_window_dimensions(cfg)

        top = cfg.get("screen.availTop", 0) or 0
        assert top + cfg["screen.availHeight"] <= cfg["screen.height"], (
            f"availTop={top} left over from the discarded device: "
            f"{top}+{cfg['screen.availHeight']} > {cfg['screen.height']}"
        )
        assert cfg.get("screen.availLeft", 0) + cfg["screen.availWidth"] <= cfg["screen.width"]
        # Window keys are not emitted for every fingerprint, so only assert nesting
        # when they are actually present.
        inner, outer = cfg.get("window.innerWidth"), cfg.get("window.outerWidth")
        if inner and outer:
            assert inner <= outer <= cfg["screen.availWidth"]


# ---------------------------------------------------------------------------
# Wiring: the resample must reach the generated config
# ---------------------------------------------------------------------------


def test_pinned_screen_predicate_covers_every_way_of_choosing_one():
    """B2's decision logic, tested without a binary. The launch_options test below
    proves the same thing end to end but skips wherever no browser is installed,
    including CI -- which is how the original override shipped unnoticed."""
    from browserforge.fingerprints import Screen

    from camoufox.utils import _caller_pinned_screen as pinned

    assert pinned(None, None, None, None) is False           # default path resamples
    assert pinned(None, None, None, True) is False           # opt-in presets, not pinned
    assert pinned(Screen(max_width=1280), None, None, None) is True
    assert pinned(None, (1600, 1000), None, None) is True
    assert pinned(None, None, object(), None) is True        # caller-supplied fingerprint
    assert pinned(None, None, None, {"screen": {}}) is True  # pinned preset dict


def _binary():
    for c in (os.environ.get("CFX_BIN"),
              "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"):
        if c and os.path.exists(c):
            return c
    return None


def _launch_config(**kwargs):
    """Drive the real launch_options.

    executable_path is MANDATORY here, never optional: without it launch_options
    resolves the installed browser and will DOWNLOAD ~312MB if none is present. A
    test suite must never do that, so these tests skip instead (see _binary()).
    """
    import json

    from camoufox.utils import launch_options

    lo = launch_options(headless=True, os="macos", ff_version=152,
                        i_know_what_im_doing=True, executable_path=_binary(), **kwargs)
    env = lo["env"]
    return json.loads("".join(
        env[k] for k in sorted((k for k in env if k.startswith("CAMOU_CONFIG_")),
                               key=lambda k: int(k.rsplit("_", 1)[1]))
    ))


@pytest.mark.skipif(_binary() is None, reason="needs a Camoufox binary (set CFX_BIN)")
def test_explicit_screen_constraint_is_not_discarded():
    """A caller's screen= is a MAX constraint. The other fixups only ever shrink, so
    they cannot violate it; this one REPLACES the screen, so it must not run at all
    when the caller pinned one."""
    from browserforge.fingerprints import Screen

    for _ in range(15):
        cfg = _launch_config(screen=Screen(max_width=1280, max_height=800))
        assert cfg["screen.width"] <= 1280, f"screen= was discarded: {cfg['screen.width']}"
        assert cfg["screen.height"] <= 800


@pytest.mark.skipif(_binary() is None, reason="needs a Camoufox binary (set CFX_BIN)")
def test_resample_still_runs_when_nothing_is_pinned(monkeypatch):
    """Guard against over-correcting B2 into a no-op for the default path.

    Asserts the call happened rather than inspecting the drawn screen: ~16% of macOS
    fingerprints already have dpr~1, and those are correctly NOT resampled, so their
    screen comes from browserforge and need not be in the preset pool. An
    "every draw is in the pool" assertion looks stricter but is simply flaky.
    """
    from camoufox import utils

    seen_dprs = []
    real = utils.resample_screen_for_dpr1

    def spy(config, target_os, source_dpr, ff_version=None):
        seen_dprs.append(source_dpr)
        return real(config, target_os, source_dpr, ff_version)

    monkeypatch.setattr(utils, "resample_screen_for_dpr1", spy)
    for _ in range(8):
        _launch_config()

    assert seen_dprs, "resample_screen_for_dpr1 was never reached on the default path"
    assert any(d and abs(d - 1) > 0.02 for d in seen_dprs), (
        f"never invoked with a scaled-display dpr in 8 draws: {seen_dprs}"
    )


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
