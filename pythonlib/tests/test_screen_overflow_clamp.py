"""
Regression test for daijro/camoufox#118: a generated fingerprint can put
window.outerWidth > screen.width or window.outerHeight > screen.availHeight --
a window bigger than the screen, which is physically impossible and detectable.
launch_options() clamps with clamp_window_dimensions().
"""
from camoufox.fingerprints import clamp_window_dimensions
from camoufox.utils import launch_options

import orjson


def test_clamp_shrinks_oversized_outer_dims():
    config = {
        'screen.width': 1280, 'screen.height': 720,
        'screen.availWidth': 1280, 'screen.availHeight': 720,
        'window.outerWidth': 1920,  # bigger than the screen
        'window.outerHeight': 1080,
        'window.innerWidth': 1900,
        'window.innerHeight': 1060,
    }
    clamp_window_dimensions(config)

    assert config['window.outerWidth'] <= config['screen.availWidth']
    assert config['window.outerHeight'] <= config['screen.availHeight']
    assert config['window.innerWidth'] <= config['window.outerWidth']
    assert config['window.innerHeight'] <= config['window.outerHeight']


def test_clamp_leaves_valid_dims_untouched():
    config = {
        'screen.width': 1920, 'screen.height': 1080,
        'screen.availWidth': 1920, 'screen.availHeight': 1040,
        'window.outerWidth': 1280, 'window.outerHeight': 800,
        'window.innerWidth': 1264, 'window.innerHeight': 760,
    }
    original = dict(config)
    clamp_window_dimensions(config)
    assert config == original


def test_clamp_handles_missing_keys_gracefully():
    config = {'window.outerWidth': 1920, 'window.outerHeight': 1080}
    clamp_window_dimensions(config)
    assert config == {'window.outerWidth': 1920, 'window.outerHeight': 1080}


def test_launched_windows_never_exceed_the_screen():
    for os_name in ('linux', 'windows', 'macos'):
        for _ in range(5):
            opts = launch_options(os=os_name, headless=True, i_know_what_im_doing=True)
            env = opts['env']
            chunks = sorted((int(k.rsplit('_', 1)[1]), v) for k, v in env.items() if k.startswith('CAMOU_CONFIG_'))
            cfg = orjson.loads(''.join(v for _, v in chunks))
            for axis in ('Width', 'Height'):
                screen, outer = cfg.get(f'screen.{axis.lower()}'), cfg.get(f'window.outer{axis}')
                if screen and outer:
                    assert outer <= screen, (os_name, axis, cfg)
