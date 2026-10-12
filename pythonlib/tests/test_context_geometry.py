"""#164: NewContext's geometry must fit the launch window, which is process-wide."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from camoufox.fingerprints import generate_context_fingerprint  # noqa: E402

LW = {"outer": (1366, 728), "inner": (1366, 643), "screen": (1366, 768)}


def test_viewport_is_the_launch_inner_and_the_screen_holds_the_window():
    for _ in range(200):
        fp = generate_context_fingerprint(os="windows", launch_window=LW)
        vp = fp["context_options"]["viewport"]
        assert (vp["width"], vp["height"]) == LW["inner"]
        sw, sh = fp["config"]["screen.width"], fp["config"]["screen.height"]
        assert sw >= LW["outer"][0] and sh >= LW["outer"][1], (sw, sh)
        assert f"w.setScreenDimensions({sw}, {sh})" in fp["init_script"]


def test_no_launch_inner_means_no_viewport_and_no_scale_factor():
    lw = {**LW, "inner": (None, None)}
    opts = generate_context_fingerprint(os="macos", launch_window=lw)["context_options"]
    assert opts.get("no_viewport") is True
    assert "viewport" not in opts and "device_scale_factor" not in opts


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
    assert b.opts.get("no_viewport") is True and "viewport" not in b.opts
    NewContext(b, os="windows", viewport={"width": 800, "height": 600})
    assert b.opts["viewport"] == {"width": 800, "height": 600} and "no_viewport" not in b.opts
