"""#164: NewContext's geometry must fit the launch window, which is process-wide."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from camoufox.fingerprints import generate_context_fingerprint, get_random_preset  # noqa: E402

LW = {"outer": (1366, 728), "inner": (1366, 643), "screen": (1366, 768)}


def test_viewport_is_the_launch_inner_and_the_screen_holds_the_window():
    for _ in range(200):
        fp = generate_context_fingerprint(os="windows", launch_window=LW)
        vp = fp["context_options"]["viewport"]
        assert (vp["width"], vp["height"]) == LW["inner"]
        sw, sh = fp["config"]["screen.width"], fp["config"]["screen.height"]
        assert sw >= LW["outer"][0] and sh >= LW["outer"][1], (sw, sh)
        assert f"w.setScreenDimensions({sw}, {sh})" in fp["init_script"]


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_no_launch_inner_keeps_the_preset_viewport_inside_the_outer_window_and_its_scale_factor(os_name):
    # fpgen leaves window.inner* unmapped, so this is the default NewContext path.
    lw = {**LW, "inner": (None, None)}
    ow, oh = lw["outer"]
    clamped = 0
    for _ in range(200):
        preset = get_random_preset(os_name)
        opts = generate_context_fingerprint(preset=preset, launch_window=lw)["context_options"]
        assert "no_viewport" not in opts
        vp = opts["viewport"]
        # clamp_window_dimensions' convention: inner <= outer, no fixed chrome margin.
        assert vp["width"] <= ow and vp["height"] <= oh, (vp, lw["outer"])
        assert opts.get("device_scale_factor") == preset["screen"].get("devicePixelRatio")
        clamped += (vp["width"], vp["height"]) != (preset["screen"]["width"], max(preset["screen"]["height"] - 28, 600))
    assert clamped, "no draw exercised the clamp"


def test_attach_launch_window_reads_the_launch_config_and_defaults_outer():
    import orjson
    from camoufox.utils import attach_launch_window

    class B:
        pass

    cfg = {"window.innerWidth": 1000, "window.innerHeight": 600, "screen.width": 1920, "screen.height": 1080}
    b = attach_launch_window(B(), {"env": {"CAMOU_CONFIG_1": orjson.dumps(cfg).decode()}})
    assert b._camoufox_launch_window == {
        "outer": (1280, 1040), "inner": (1000, 600), "screen": (1920, 1080),
    }


def test_new_context_passes_the_launch_window_and_an_explicit_viewport_wins():
    from camoufox.sync_api import NewContext

    class Ctx:
        def add_init_script(self, _):
            pass

    class B:
        version = "156.0"
        _camoufox_launch_window = {**LW, "inner": (None, None)}

        def new_context(self, **opts):
            self.opts = opts
            return Ctx()

    b = B()
    NewContext(b, os="windows")
    assert "no_viewport" not in b.opts
    assert b.opts["viewport"]["width"] <= LW["outer"][0] and b.opts["viewport"]["height"] <= LW["outer"][1]
    NewContext(b, os="windows", viewport={"width": 800, "height": 600})
    assert b.opts["viewport"] == {"width": 800, "height": 600} and "no_viewport" not in b.opts


def test_a_mock_or_malformed_launch_window_behaves_as_none():
    from unittest import mock

    def shape(fp):
        o = fp["context_options"]
        return {k: o.get(k) is not None for k in ("viewport", "no_viewport", "device_scale_factor")}

    base = shape(generate_context_fingerprint(os="windows", launch_window=None))
    for bad in (mock.MagicMock(), {"outer": (1, 2)}, {"outer": 1, "inner": 2, "screen": 3}, "x"):
        assert shape(generate_context_fingerprint(os="windows", launch_window=bad)) == base


def test_new_context_with_a_mock_browser_does_not_crash():
    from unittest import mock
    from camoufox.sync_api import NewContext

    b = mock.MagicMock()
    b.version = "156.0"
    NewContext(b, os="windows")
    assert "viewport" in b.new_context.call_args.kwargs


def test_explicit_no_viewport_drops_the_generated_viewport_and_scale_factor():
    import asyncio
    from unittest import mock
    from camoufox.async_api import AsyncNewContext
    from camoufox.sync_api import NewContext

    sb = mock.MagicMock(version="156.0", _camoufox_launch_window=LW)
    NewContext(sb, os="windows", no_viewport=True)
    o = sb.new_context.call_args.kwargs
    assert o["no_viewport"] is True and "viewport" not in o and "device_scale_factor" not in o

    # The default path (no launch inner) with a dpr-2 preset: the caller's no_viewport still
    # drops the generated viewport and device_scale_factor.
    preset = next(p for p in iter(lambda: get_random_preset("macos"), None)
                  if p["screen"].get("devicePixelRatio") == 2)
    nb = mock.MagicMock(version="156.0", _camoufox_launch_window={**LW, "inner": (None, None)})
    NewContext(nb, preset=preset)
    assert nb.new_context.call_args.kwargs["device_scale_factor"] == 2
    NewContext(nb, preset=preset, no_viewport=True)
    o = nb.new_context.call_args.kwargs
    assert o["no_viewport"] is True and "viewport" not in o and "device_scale_factor" not in o

    ab = mock.MagicMock(version="156.0", _camoufox_launch_window=LW)
    ab.new_context = mock.AsyncMock()
    ab.new_context.return_value.add_init_script = mock.AsyncMock()
    asyncio.run(AsyncNewContext(ab, os="windows", no_viewport=True))
    o = ab.new_context.call_args.kwargs
    assert o["no_viewport"] is True and "viewport" not in o and "device_scale_factor" not in o
