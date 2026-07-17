"""
Regression coverage for daijro/camoufox#328: fonts:spacing_seed, audio:seed and
canvas:seed were re-randomized on every launch, with no way to pin them for a
reproducible fingerprint.

* from_preset() (fingerprints.py ~314-317) had *no* parameter through which a
  caller could supply these seeds -- it always overwrote them with a fresh
  random value, unconditionally. This was the actual bug: fixed by adding
  optional fonts_spacing_seed/audio_seed/canvas_seed kwargs (still random by
  default, when left unset).

* launch_options()'s config dict (utils.py ~707-709) already only randomizes a
  seed when the key is *absent*, via set_into(). A caller pre-populating
  config={'fonts:spacing_seed': N, ...} before calling launch_options()/
  Camoufox() already survives through both the BrowserForge and preset paths
  -- verified empirically below. No source change was needed for that half;
  the test locks the existing (correct) behavior in as a regression guard.

Run with:
    cd camoufox && PYTHONPATH=pythonlib python3 -m pytest pythonlib/tests/test_seed_pinning.py -v
"""
import json
import os
import sys
from pathlib import Path

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.addons import DefaultAddons  # noqa: E402
from camoufox.fingerprints import from_preset  # noqa: E402
from camoufox.utils import launch_options  # noqa: E402

MINIMAL_PRESET = {
    'navigator': {
        'userAgent': 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0',
        'platform': 'Linux x86_64',
    },
    'screen': {'width': 1920, 'height': 1080},
    'webgl': {},
}


# --- from_preset(): the actually-broken piece -------------------------------

def test_from_preset_pins_seeds_when_given():
    config = from_preset(MINIMAL_PRESET, fonts_spacing_seed=111, audio_seed=222, canvas_seed=333)
    assert config['fonts:spacing_seed'] == 111
    assert config['audio:seed'] == 222
    assert config['canvas:seed'] == 333


def test_from_preset_still_randomizes_when_unset():
    # Default behavior (no pinning) must be unchanged: two calls get different seeds.
    config_a = from_preset(MINIMAL_PRESET)
    config_b = from_preset(MINIMAL_PRESET)
    assert config_a['fonts:spacing_seed'] != config_b['fonts:spacing_seed']
    assert config_a['audio:seed'] != config_b['audio:seed']
    assert config_a['canvas:seed'] != config_b['canvas:seed']


def test_from_preset_partial_pin_still_randomizes_the_rest():
    config = from_preset(MINIMAL_PRESET, fonts_spacing_seed=999)
    assert config['fonts:spacing_seed'] == 999
    assert config['audio:seed'] != 999
    assert config['canvas:seed'] != 999


# --- launch_options(): already correct, locked in as a regression guard -----

def test_launch_options_preserves_pinned_seeds_via_config_dict(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent.parent
    props_src = repo_root / 'settings' / 'properties.json'
    (tmp_path / 'properties.json').write_bytes(props_src.read_bytes())
    fake_exe = tmp_path / 'camoufox-bin'
    fake_exe.write_bytes(b'')

    result = launch_options(
        config={'fonts:spacing_seed': 111222, 'audio:seed': 333444, 'canvas:seed': 555666},
        headless=True,
        os='linux',
        exclude_addons=[DefaultAddons.UBO],  # skip network addon download
        executable_path=str(fake_exe),  # skip the "camoufox not installed" check
        env={},
    )

    camou_chunks = sorted(
        ((k, v) for k, v in result['env'].items() if k.startswith('CAMOU_CONFIG')),
        key=lambda kv: int(kv[0].rsplit('_', 1)[1]),
    )
    cfg = json.loads(''.join(v for _, v in camou_chunks))

    assert cfg['fonts:spacing_seed'] == 111222
    assert cfg['audio:seed'] == 333444
    assert cfg['canvas:seed'] == 555666
