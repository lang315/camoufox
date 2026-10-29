"""browser/scripts/patch.py adds Rust targets with the rustup on PATH (#335), not one in ~/.cargo/bin."""

import importlib.util
import os
import stat
import sys

import pytest

from ci._util import BROWSER_ROOT

sys.path.insert(0, str(BROWSER_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("camoufox_patch", BROWSER_ROOT / "scripts" / "patch.py")
patch = importlib.util.module_from_spec(spec)
argv, sys.argv = sys.argv, ["patch.py"]  # patch.py parses sys.argv at import
spec.loader.exec_module(patch)
sys.argv = argv


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A HOME with no ~/.cargo, as on a runner image whose rustup lives elsewhere."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path


def test_target_is_added_by_the_rustup_on_path(home, monkeypatch):
    bindir = home / "bin"
    bindir.mkdir()
    calls = home / "calls"
    exe = bindir / "rustup"
    exe.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin")

    patch.add_rustup("x86_64-apple-darwin")

    assert calls.read_text().strip() == "target add x86_64-apple-darwin"


def test_missing_rustup_fails_the_build(home, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    with pytest.raises(SystemExit) as e:
        patch.add_rustup("x86_64-apple-darwin")

    assert e.value.code == 1
