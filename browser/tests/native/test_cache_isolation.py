"""The suite never touches the developer's real camoufox cache (#489).

The cache constants are computed when camoufox is first imported, so conftest.py
redirects the environment before that import (python/tests/cache_root.py, shared
with the Python suite, #280) and checks the result at session start.
"""

import os
import tempfile
from pathlib import Path

import pytest

import cache_root
from camoufox import pkgman

TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


def test_the_launcher_cache_is_under_the_temp_root():
    assert pkgman.INSTALL_DIR.resolve().is_relative_to(TEMP_ROOT)


@pytest.mark.parametrize("var", ["HOME", "USERPROFILE", "LOCALAPPDATA", "XDG_CACHE_HOME"])
def test_cache_environment_is_under_the_temp_root(var):
    assert Path(os.environ[var]).resolve().is_relative_to(TEMP_ROOT)


def test_guard_accepts_the_suite_as_configured():
    assert cache_root.cache_paths_outside(cache_root.ROOT) == []


def test_guard_rejects_a_constant_outside_the_root(monkeypatch, tmp_path):
    monkeypatch.setattr(pkgman, "INSTALL_DIR", tmp_path / "elsewhere" / "camoufox")
    assert any("pkgman.INSTALL_DIR" in p for p in cache_root.cache_paths_outside(cache_root.ROOT))
