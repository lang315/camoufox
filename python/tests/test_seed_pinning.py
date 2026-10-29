"""
Regression coverage for daijro/camoufox#328: canvas:seed was re-randomized on
every launch, with no way to pin it (so was audio:seed, which no longer exists:
audio renders as stock Firefox does). Pinning goes through the `config` dict;
the glyph-spacing seed no longer exists (D2).

* launch_options()'s config dict (utils.py ~707-709) already only randomizes a
  seed when the key is *absent*, via set_into(). A caller pre-populating
  config={'fonts:spacing_seed': N, ...} before calling launch_options()/
  Camoufox() already survives through both the BrowserForge and preset paths
  -- verified empirically below. No source change was needed for that half;
  the test locks the existing (correct) behavior in as a regression guard.

Run with:
    cd camoufox && PYTHONPATH=python/src python3 -m pytest python/tests/test_seed_pinning.py -v
"""
import json
import os
import sys
from pathlib import Path

# Make `import camoufox` resolve to the in-tree python/src without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from camoufox import utils  # noqa: E402
from camoufox.addons import DefaultAddons  # noqa: E402
from camoufox.utils import launch_options  # noqa: E402

# --- launch_options(): already correct, locked in as a regression guard -----

def test_launch_options_preserves_pinned_seeds_via_config_dict(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parent.parent.parent
    props_src = repo_root / 'browser' / 'settings' / 'properties.json'
    (tmp_path / 'properties.json').write_bytes(props_src.read_bytes())
    fake_exe = tmp_path / 'camoufox-bin'
    fake_exe.write_bytes(b'')

    # On Linux, get_env_vars() reads the bundled fontconfig from beside the
    # supplied binary (upstream fc3392e) instead of from the managed install,
    # so this fake bundle has to carry one. See test_executable_path_bundle.py.
    (tmp_path / 'fontconfig' / 'linux').mkdir(parents=True)
    (tmp_path / 'fontconfig' / 'linux' / 'fonts.conf').write_text(
        '<?xml version="1.0"?><fontconfig><dir prefix="cwd">fonts</dir></fontconfig>'
    )
    (tmp_path / 'fonts' / 'L').mkdir(parents=True)
    (tmp_path / 'fonts' / 'groups.json').write_text('{"readBy": {"lin": ["L"]}}')
    # The generated runtime conf goes to the cache dir; keep it out of the real one.
    monkeypatch.setattr(utils, 'INSTALL_DIR', tmp_path / 'cache')
    # resolve_verstr() reads the supplied build's own version, and raises without one.
    (tmp_path / 'application.ini').write_text('[App]\nVersion=150.0.2-beta.25\n')

    result = launch_options(
        config={'canvas:seed': 555666},
        headless=True,
        os='linux',
        exclude_addons=[DefaultAddons.UBO],  # the fake build bundles no addon
        executable_path=str(fake_exe),  # so get_env_vars() reads the fontconfig bundle above
        env={},
    )

    camou_chunks = sorted(
        ((k, v) for k, v in result['env'].items() if k.startswith('CAMOU_CONFIG')),
        key=lambda kv: int(kv[0].rsplit('_', 1)[1]),
    )
    cfg = json.loads(''.join(v for _, v in camou_chunks))

    assert cfg['canvas:seed'] == 555666
