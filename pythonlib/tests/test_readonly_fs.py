"""
Tests for camoufox.utils._check_writable_dirs.

Regression for daijro/camoufox#572: launching Camoufox with HOME (or the
platform cache dir) on a read-only filesystem made the browser subprocess
hang for ~180s (glxtest/fontconfig/profile all need a writable HOME) instead
of failing with a clear error. This preflight check must raise before the
browser is spawned.

Run with:
    cd pythonlib && python -m pytest tests/test_readonly_fs.py -v
"""

import os
import sys

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import utils  # noqa: E402
from camoufox.exceptions import NotWritableError  # noqa: E402


def test_writable_dirs_pass(tmp_path, monkeypatch):
    """Sanity check: no exception when both HOME and the cache dir are writable."""
    monkeypatch.setattr(utils, "user_cache_dir", lambda name: str(tmp_path / "cache"))
    utils._check_writable_dirs({"HOME": str(tmp_path)})


def test_readonly_home_raises_via_os_access_mock(tmp_path, monkeypatch):
    """A HOME whose write bit is unavailable (mocked os.access) must raise clearly."""
    monkeypatch.setattr(utils, "user_cache_dir", lambda name: str(tmp_path / "cache"))

    home = tmp_path / "home"
    home.mkdir()
    real_access = os.access

    def fake_access(path, mode):
        if str(path) == str(home) and mode == os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)

    with pytest.raises(NotWritableError, match="HOME"):
        utils._check_writable_dirs({"HOME": str(home)})


def test_readonly_cache_dir_raises_via_os_access_mock(tmp_path, monkeypatch):
    """An unwritable cache dir parent must raise clearly, independent of HOME."""
    home = tmp_path / "home_ok"
    home.mkdir()  # exists and writable, so the HOME check passes first

    cache_parent = tmp_path / "cache_parent"
    cache_parent.mkdir()
    cache_dir = cache_parent / "camoufox"  # does not exist yet
    monkeypatch.setattr(utils, "user_cache_dir", lambda name: str(cache_dir))

    real_access = os.access

    def fake_access(path, mode):
        if str(path) == str(cache_parent) and mode == os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)

    with pytest.raises(NotWritableError, match="cache directory"):
        utils._check_writable_dirs({"HOME": str(home)})


@pytest.mark.skipif(os.name != "posix", reason="chmod-based read-only dir is POSIX-only")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bypasses permission bits")
def test_readonly_home_raises_via_real_chmod(tmp_path, monkeypatch):
    """A real 0o500 (read+execute, no write) HOME directory must raise."""
    monkeypatch.setattr(utils, "user_cache_dir", lambda name: str(tmp_path / "cache"))

    home = tmp_path / "ro_home"
    home.mkdir()
    home.chmod(0o500)
    try:
        with pytest.raises(NotWritableError, match="HOME"):
            utils._check_writable_dirs({"HOME": str(home)})
    finally:
        home.chmod(0o700)  # restore so tmp_path cleanup can remove it
