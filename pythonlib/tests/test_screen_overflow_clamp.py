"""
Regression test for daijro/camoufox#118: browserforge's raw fingerprint can
put window.outerWidth > screen.width or window.outerHeight > screen.availHeight
-- a window bigger than the screen, which is a physical impossibility and a
detectable tell. from_browserforge() (via clamp_window_to_screen) must clamp
outer/inner window dimensions to the screen.

Run with:
    cd camoufox && PYTHONPATH=pythonlib python3 -m pytest pythonlib/tests/test_screen_overflow_clamp.py -v
"""
import os
import sys

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import (  # noqa: E402
    clamp_window_to_screen,
    from_browserforge,
    generate_fingerprint,
)


def test_clamp_shrinks_oversized_outer_dims():
    camoufox_data = {
        'screen.width': 1280,
        'screen.availHeight': 720,
        'window.outerWidth': 1920,  # bigger than screen.width -- impossible
        'window.outerHeight': 1080,  # bigger than screen.availHeight -- impossible
        'window.innerWidth': 1900,
        'window.innerHeight': 1060,
    }
    clamp_window_to_screen(camoufox_data)

    assert camoufox_data['window.outerWidth'] <= camoufox_data['screen.width']
    assert camoufox_data['window.outerHeight'] <= camoufox_data['screen.availHeight']
    assert camoufox_data['window.innerWidth'] <= camoufox_data['window.outerWidth']
    assert camoufox_data['window.innerHeight'] <= camoufox_data['window.outerHeight']


def test_clamp_leaves_valid_dims_untouched():
    camoufox_data = {
        'screen.width': 1920,
        'screen.availHeight': 1040,
        'window.outerWidth': 1280,
        'window.outerHeight': 800,
        'window.innerWidth': 1264,
        'window.innerHeight': 760,
    }
    original = dict(camoufox_data)
    clamp_window_to_screen(camoufox_data)
    assert camoufox_data == original


def test_clamp_handles_missing_keys_gracefully():
    # screen.width/availHeight absent (e.g. browserforge omitted them) -- must not crash.
    camoufox_data = {'window.outerWidth': 1920, 'window.outerHeight': 1080}
    clamp_window_to_screen(camoufox_data)
    assert camoufox_data == {'window.outerWidth': 1920, 'window.outerHeight': 1080}


def test_from_browserforge_clamps_real_fingerprint_overflow():
    # Build a real Fingerprint via BrowserForge, then force the exact physically
    # impossible condition #118 describes before feeding it through from_browserforge().
    fp = generate_fingerprint(os='linux')
    fp.screen.outerWidth = fp.screen.width + 500
    fp.screen.outerHeight = fp.screen.availHeight + 300

    data = from_browserforge(fp)

    assert data['window.outerWidth'] <= data['screen.width']
    assert data['window.outerHeight'] <= data['screen.availHeight']
