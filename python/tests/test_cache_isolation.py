"""The suite never touches the developer's real camoufox cache (#279).

The cache constants are computed when camoufox is first imported, so conftest.py
redirects the environment before that import and checks the result at session
start.
"""

import os
import tempfile
from pathlib import Path

import pytest

from camoufox import addons, geolocation, multiversion, pkgman

from conftest import CACHE_ROOT

CACHE_CONSTANTS = {
    "pkgman.INSTALL_DIR": pkgman.INSTALL_DIR,
    "geolocation.GEOIP_DIR": geolocation.GEOIP_DIR,
    "geolocation.MMDB_DIR": geolocation.MMDB_DIR,
    "geolocation.GEOIP_CONFIG": geolocation.GEOIP_CONFIG,
    "multiversion.BROWSERS_DIR": multiversion.BROWSERS_DIR,
    "multiversion.CONFIG_FILE": multiversion.CONFIG_FILE,
    "multiversion.REPO_CACHE_FILE": multiversion.REPO_CACHE_FILE,
    "multiversion.COMPAT_FLAG": multiversion.COMPAT_FLAG,
}
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


@pytest.mark.parametrize("name", CACHE_CONSTANTS)
def test_cache_constant_is_under_the_temp_root(name):
    assert CACHE_CONSTANTS[name].resolve().is_relative_to(TEMP_ROOT)


@pytest.mark.parametrize("var", ["HOME", "USERPROFILE", "LOCALAPPDATA", "XDG_CACHE_HOME"])
def test_cache_environment_is_under_the_temp_root(var):
    assert Path(os.environ[var]).resolve().is_relative_to(TEMP_ROOT)


def test_addons_dir_is_redirected_per_test(tmp_path):
    assert addons.ADDONS_DIR.is_relative_to(tmp_path)


def test_guard_accepts_the_suite_as_configured(cache_paths_outside_root):
    assert cache_paths_outside_root(CACHE_ROOT) == []


def test_guard_rejects_a_constant_outside_the_root(cache_paths_outside_root, monkeypatch, tmp_path):
    monkeypatch.setattr(pkgman, "INSTALL_DIR", tmp_path / "elsewhere" / "camoufox")
    assert any("pkgman.INSTALL_DIR" in p for p in cache_paths_outside_root(CACHE_ROOT))


def test_a_test_starts_with_an_empty_cache():
    leftover = list(CACHE_ROOT.iterdir())
    assert leftover == []
    (CACHE_ROOT / "written-by-this-test").write_text("x")
