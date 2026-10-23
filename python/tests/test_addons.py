"""
Tests for camoufox.addons default-addon download/caching.

Regression guard for #308 (daijro/camoufox#308): a partial/failed first
download leaves an empty addon directory behind. The old "already downloaded"
check was a bare os.path.exists(dir), so that empty dir was trusted forever and
every later launch raised InvalidAddonPath ("manifest.json is missing"),
unrecoverable short of manually deleting the cache.

Run with:
    cd python && python -m pytest tests/test_addons.py -v
"""

import os
import threading
import time
from types import SimpleNamespace

import pytest

from camoufox import addons
from camoufox import addons as addons_mod
from camoufox.addons import DefaultAddons, add_default_addons, maybe_download_addons

ADDON = SimpleNamespace(name="fakeaddon", value="https://example.invalid/x.xpi")

UBO = DefaultAddons.UBO.name


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


def test_failed_download_removes_partial_dir_fake_addon(tmp_path, monkeypatch):
    def boom(url, path, name):
        os.makedirs(path, exist_ok=True)  # partial dir gets created…
        raise RuntimeError("network down")

    monkeypatch.setattr(addons, "get_addon_path", lambda n: str(tmp_path / n))
    monkeypatch.setattr(addons, "download_and_extract", boom)

    out = []
    addons.maybe_download_addons([ADDON], out)  # must not raise

    assert not (tmp_path / ADDON.name).exists()  # …then cleaned up
    assert out == []                             # bad path not advertised


@pytest.fixture
def addons_dir(tmp_path, monkeypatch):
    # Point the addon store at a throwaway dir so no real cache is touched.
    root = tmp_path / "addons"
    monkeypatch.setattr(addons_mod, "get_addon_path", lambda name: str(root / name))
    return root


def _write_manifest(url, extract_path, name):
    os.makedirs(extract_path, exist_ok=True)
    with open(os.path.join(extract_path, "manifest.json"), "w") as f:
        f.write("{}")


def test_partial_dir_is_redownloaded(addons_dir, monkeypatch):
    # Leftover empty dir from a failed first download.
    partial = addons_dir / UBO
    partial.mkdir(parents=True)
    assert not (partial / "manifest.json").exists()

    calls = []

    def fake(url, extract_path, name):
        calls.append(name)
        _write_manifest(url, extract_path, name)

    monkeypatch.setattr(addons_mod, "download_and_extract", fake)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)

    # An empty dir must trigger a re-download, not be trusted.
    assert calls == [UBO]
    assert (partial / "manifest.json").exists()
    assert out == [str(partial)]


def test_extracted_addon_is_not_redownloaded(addons_dir, monkeypatch):
    path = addons_dir / UBO
    path.mkdir(parents=True)
    (path / "manifest.json").write_text("{}")

    def boom(*a, **k):
        raise AssertionError("must not re-download an already-extracted addon")

    monkeypatch.setattr(addons_mod, "download_and_extract", boom)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)
    assert out == [str(path)]


def test_failed_download_removes_partial_dir(addons_dir, monkeypatch):
    path = addons_dir / UBO

    def fail(url, extract_path, name):
        os.makedirs(extract_path, exist_ok=True)  # partial write, then die
        raise RuntimeError("network died mid-download")

    monkeypatch.setattr(addons_mod, "download_and_extract", fail)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)

    # The partial dir must be gone so the next run re-downloads instead of
    # trusting an addon that has no manifest.json.
    assert not path.exists()
    assert out == []


def test_fetcher_guard_escapes_the_addon_download_swallow(tmp_path):
    """The autouse guard (#108) must fail a test that reaches the addon download.

    maybe_download_addons catches Exception and continues, which is product behaviour
    (an offline launch still works without uBO). The guard raises through
    pytest.fail(), whose exception is a BaseException, so it is not caught
    there (#110).
    """
    with pytest.raises(pytest.fail.Exception, match=r"reached the browser fetcher"):
        # Through maybe_download_addons, so its except-Exception is on
        # the stack: a guard raising a plain Exception would be swallowed here and
        # this test would fail to raise.
        maybe_download_addons([DefaultAddons.UBO], [])


def test_concurrent_launches_download_once(addons_dir, monkeypatch):
    # Two launches in one process share the check-then-extract. A lock created
    # per call guarded nothing, so both saw no manifest and both downloaded.
    calls = []

    def slow(url, extract_path, name):
        calls.append(name)
        time.sleep(0.2)
        _write_manifest(url, extract_path, name)

    monkeypatch.setattr(addons_mod, "download_and_extract", slow)

    outs = [[], []]
    threads = [threading.Thread(target=add_default_addons, args=(out,)) for out in outs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls == [UBO]
    assert outs == [[str(addons_dir / UBO)]] * 2


def test_extraction_appears_complete_or_not_at_all(tmp_path, monkeypatch):
    # Another process checks for manifest.json without the lock, so the addon
    # directory must never hold a manifest while its other files are missing.
    target = tmp_path / UBO
    target.mkdir()
    seen = []

    def fake_unzip(buffer, extract_path, desc=None, bar=True):
        seen.append((target / "manifest.json").exists())
        _write_manifest(None, extract_path, UBO)
        with open(os.path.join(extract_path, "background.js"), "w") as f:
            f.write("")
        seen.append((target / "manifest.json").exists())

    monkeypatch.setattr(addons_mod, "webdl", lambda *a, **k: b"")
    monkeypatch.setattr(addons_mod, "unzip", fake_unzip)

    addons_mod.download_and_extract("url", str(target), UBO)

    assert seen == [False, False]
    assert sorted(os.listdir(target)) == ["background.js", "manifest.json"]
    assert os.listdir(tmp_path) == [UBO]


def test_complete_addon_installed_meanwhile_is_kept(tmp_path, monkeypatch):
    # Another process can finish installing the addon while this one extracts.
    # Its copy may already be loading in a browser, so it must not be deleted.
    target = tmp_path / UBO
    target.mkdir()

    def fake_unzip(buffer, extract_path, desc=None, bar=True):
        _write_manifest(None, extract_path, UBO)
        _write_manifest(None, str(target), UBO)
        with open(target / "theirs.js", "w") as f:
            f.write("")

    monkeypatch.setattr(addons_mod, "webdl", lambda *a, **k: b"")
    monkeypatch.setattr(addons_mod, "unzip", fake_unzip)

    addons_mod.download_and_extract("url", str(target), UBO)

    assert sorted(os.listdir(target)) == ["manifest.json", "theirs.js"]
    assert os.listdir(tmp_path) == [UBO]


def test_failed_download_keeps_complete_addon(addons_dir, monkeypatch):
    # This launch's download fails after another process installed the addon.
    # That copy may already be loading in a browser, so it must not be deleted.
    path = addons_dir / UBO

    def fail(url, extract_path, name):
        _write_manifest(url, str(path), name)
        raise RuntimeError("network died mid-download")

    monkeypatch.setattr(addons_mod, "download_and_extract", fail)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)

    assert (path / "manifest.json").exists()
    assert out == []
