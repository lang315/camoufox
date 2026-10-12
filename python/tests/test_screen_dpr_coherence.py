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
strictly worse — see browser/tests/build-tester/observer/probe_split.py.

Run with:
    cd camoufox && PYTHONPATH=python/src python3 -m pytest \
        python/tests/test_screen_dpr_coherence.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
    return {"screen.width": w, "screen.height": h}


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


def scaled_macos_configs():
    """from_preset configs of the bundled macOS presets recorded at dpr != 1."""
    from camoufox.fingerprints import from_preset

    for preset in load_presets(152)["presets"]["macos"]:
        dpr = preset.get("screen", {}).get("devicePixelRatio")
        if dpr and abs(dpr - 1) >= 0.02:
            yield from_preset(preset, "152"), dpr


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
# Composition. Every test above drives a hand-built 4-key dict. This runs the
# resample over genuine from_preset configs, alongside the fixups that follow it
# in launch_options.
# ---------------------------------------------------------------------------


def test_the_swapped_screen_takes_the_baseline_avail_and_fits_the_window():
    """The resample swaps only the screen size; follow_baseline_protection then
    claims the avail the browser reports for that screen, and the window clamp
    fits inside it."""
    from camoufox.fingerprints import (
        BASELINE_TASKBAR_HEIGHT, clamp_window_dimensions, follow_baseline_protection,
    )

    seen = 0
    for cfg, dpr in scaled_macos_configs():
        resample_screen_for_dpr1(cfg, "mac", dpr, 152)
        follow_baseline_protection(cfg, "mac")
        clamp_window_dimensions(cfg)
        seen += 1

        assert cfg["screen.availWidth"] == cfg["screen.width"]
        assert cfg["screen.availHeight"] == cfg["screen.height"] - BASELINE_TASKBAR_HEIGHT["mac"]
        inner, outer = cfg.get("window.innerWidth"), cfg.get("window.outerWidth")
        if inner and outer:
            assert inner <= outer <= cfg["screen.availWidth"]
    assert seen


# ---------------------------------------------------------------------------
# Wiring: the resample must reach the generated config
# ---------------------------------------------------------------------------


def _launch_config(**kwargs):
    """Drive the real launch_options (conftest stubs the install and the addons)."""
    import json

    from camoufox.utils import launch_options

    lo = launch_options(headless=True, os="macos", ff_version=152,
                        i_know_what_im_doing=True, **kwargs)
    env = lo["env"]
    return json.loads("".join(
        env[k] for k in sorted((k for k in env if k.startswith("CAMOU_CONFIG_")),
                               key=lambda k: int(k.rsplit("_", 1)[1]))
    ))


def test_resample_does_not_run_when_the_caller_pinned_a_screen(monkeypatch):
    """A caller's screen= bounds the identity. The other fixups only ever shrink,
    so they cannot violate it; the resample REPLACES the screen, so it must not
    run when the caller pinned one, and must run when nothing is pinned."""
    from camoufox import utils
    from camoufox.fingerprints import Screen

    calls = []
    real = utils.resample_screen_for_dpr1
    monkeypatch.setattr(
        utils, "resample_screen_for_dpr1", lambda *a, **k: calls.append(a) or real(*a, **k)
    )
    for _ in range(5):
        _launch_config(fingerprint_preset=True, screen=Screen(max_width=1280, max_height=800))
    assert calls == []
    for _ in range(5):
        _launch_config(fingerprint_preset=True)
    assert calls, "resample_screen_for_dpr1 was never reached on the default preset path"


def test_headless_macos_preset_screens_are_all_real_1x_resolutions():
    valid = real_dpr1_screens("macos")
    scaled = {
        (s["width"], s["height"])
        for s in (p["screen"] for p in load_presets(152)["presets"]["macos"])
        if (s.get("devicePixelRatio") or 1) > 1.5
    }
    drawn = []
    for _ in range(30):
        cfg = _launch_config(fingerprint_preset=True)
        drawn.append((cfg.get("screen.width"), cfg.get("screen.height")))

    # A preset recorded at dpr~1 keeps its own screen; every scaled one is
    # swapped, so a 2x panel's CSS size (960x540) must never come out.
    bad = [d for d in drawn if d in scaled and d not in valid]
    assert not bad, f"screens only a scaled display reports reached a headless config: {bad}"
    assert len(set(drawn)) >= 3, f"headless macOS collapsed to {set(drawn)}"
