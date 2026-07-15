"""
Tests for camoufox.addons.maybe_download_addons.

Regression for daijro/camoufox#308: a failed/partial addon download left a
bare directory behind, which os.path.exists() then treated as "already
downloaded" forever, later tripping confirm_paths()'s manifest.json check.

Run with:
    cd pythonlib && python -m pytest tests/test_addons.py -v
"""

import os
import sys
from types import SimpleNamespace

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import addons  # noqa: E402

ADDON = SimpleNamespace(name="fakeaddon", value="https://example.invalid/x.xpi")


def _mac_manifest(path):
    """Stand-in for a successful download+extract: writes manifest.json."""
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "manifest.json"), "w") as f:
        f.write("{}")


def test_valid_existing_addon_reused_without_download(tmp_path, monkeypatch):
    addon_dir = tmp_path / ADDON.name
    _mac_manifest(str(addon_dir))  # a complete, valid addon already present

    called = []
    monkeypatch.setattr(addons, "get_addon_path", lambda n: str(tmp_path / n))
    monkeypatch.setattr(addons, "download_and_extract",
                        lambda *a, **k: called.append(a))

    out = []
    addons.maybe_download_addons([ADDON], out)

    assert called == []                 # not re-downloaded
    assert str(addon_dir) in out


def test_partial_dir_without_manifest_is_redownloaded(tmp_path, monkeypatch):
    addon_dir = tmp_path / ADDON.name
    os.makedirs(addon_dir)              # bare dir, NO manifest (partial download)

    called = []
    monkeypatch.setattr(addons, "get_addon_path", lambda n: str(tmp_path / n))
    monkeypatch.setattr(addons, "download_and_extract",
                        lambda url, path, name: (called.append(name), _mac_manifest(path)))

    out = []
    addons.maybe_download_addons([ADDON], out)

    assert called == [ADDON.name]       # re-downloaded despite the bare dir
    assert os.path.exists(addon_dir / "manifest.json")
    assert str(addon_dir) in out


def test_failed_download_removes_partial_dir(tmp_path, monkeypatch):
    def boom(url, path, name):
        os.makedirs(path, exist_ok=True)  # partial dir gets created…
        raise RuntimeError("network down")

    monkeypatch.setattr(addons, "get_addon_path", lambda n: str(tmp_path / n))
    monkeypatch.setattr(addons, "download_and_extract", boom)

    out = []
    addons.maybe_download_addons([ADDON], out)  # must not raise

    assert not (tmp_path / ADDON.name).exists()  # …then cleaned up
    assert out == []                             # bad path not advertised
