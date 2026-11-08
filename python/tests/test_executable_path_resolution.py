"""The browser is handed to Playwright by its real path (#378).

The macOS app finds libxul from the path it is started with and exits with
"Couldn't load XPCOM." for a path with a ".." component or a symlink to the
binary. launch_options must resolve both, for a str and for a Path.
"""

import os
from pathlib import Path

import pytest

from camoufox import utils

APP_INI = b"[App]\nVersion=158.0.1-beta.34\n"


@pytest.fixture
def binary(tmp_path):
    """A build laid out like a release: the binary with its files beside it."""
    bin_dir = tmp_path / "real" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "camoufox-bin"
    exe.write_bytes(b"")
    (bin_dir / "application.ini").write_bytes(APP_INI)
    return exe


@pytest.fixture(autouse=True)
def stub_identity(monkeypatch):
    """Only the path is under test; the identity steps need the fpgen model."""
    monkeypatch.setattr(utils, "generate_fingerprint", lambda *args, **kwargs: object())
    monkeypatch.setattr(utils, "from_fpgen", lambda *args, **kwargs: {})
    for name in ("add_default_addons", "get_screen_cons", "fix_navigator_arch",
                 "follow_baseline_protection", "clamp_window_dimensions",
                 "set_media_devices_defaults", "validate_config"):
        monkeypatch.setattr(utils, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "_generate_random_font_subset", lambda *args, **kwargs: [])
    monkeypatch.setattr(utils, "draw_voice_config", lambda *args, **kwargs: {"voices": []})
    monkeypatch.setattr(utils, "get_env_vars", lambda *args, **kwargs: {})


def _spellings(binary, tmp_path):
    link = tmp_path / "link" / "camoufox"
    link.parent.mkdir()
    link.symlink_to(binary)
    dotdot = os.path.join(binary.parent, "..", binary.parent.name, binary.name)
    return {"symlink": link, "dotdot": Path(dotdot)}


@pytest.mark.parametrize("kind", [str, Path], ids=["str", "Path"])
@pytest.mark.parametrize("spelling", ["symlink", "dotdot"])
def test_launch_options_resolves_the_executable_path(binary, tmp_path, spelling, kind):
    path = kind(_spellings(binary, tmp_path)[spelling])

    options = utils.launch_options(
        executable_path=path,
        os="linux",
        canvas_noise=False,
        block_webgl=True,
        headless=True,
        i_know_what_im_doing=True,
    )

    assert options["executable_path"] == str(binary.resolve())
