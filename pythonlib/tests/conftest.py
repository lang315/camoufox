"""Shared fixtures for the camoufox test suite."""

from pathlib import Path

import pytest

from camoufox import addons
from camoufox import pkgman

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def repo_get_path(file: str) -> str:
    """What a managed install would carry, read from the repo instead.

    Mirrors how `make package-linux` lays out the bundle: properties.json and
    the fontconfig tree via --includes (settings/, bundle/fontconfig), fonts via
    --fonts (bundle/fonts). get_env_vars() resolves the
    Linux fontconfig through get_path too (utils.py:319), and raises when it
    finds no fonts.conf -- settings/ has none.
    """
    head = str(file).replace("\\", "/").split("/")[0]
    if head in ("fontconfig", "fontconfigs", "fonts"):
        return str(REPO_ROOT / "bundle" / file)
    return str(REPO_ROOT / "settings" / file)


@pytest.fixture(autouse=True)
def no_browser_fetch(monkeypatch, tmp_path):
    """Fail any test that reaches the browser fetcher instead of mocking it.

    Running the suite locally used to download the browser (issue #108). Every
    entry point that ends in a network request raises here, so the offending
    test names itself rather than silently opening a socket to GitHub.

    The refusal is raised through pytest.fail(): its exception derives from
    BaseException, not Exception, so it escapes the `except Exception` that
    addons.py:94 wraps around the uBlock Origin download (#110). ADDONS_DIR is
    redirected because, with the refusal escaping, addons.py:96's rmtree no
    longer runs and a trip would leave a directory in the real user cache.
    """

    def _refuse(*args, **kwargs):
        pytest.fail("test reached the browser fetcher; mock it (#108/#110)")

    monkeypatch.setattr(pkgman.CamoufoxFetcher, "install", _refuse)
    monkeypatch.setattr(pkgman.CamoufoxFetcher, "fetch_latest", _refuse)
    monkeypatch.setattr(pkgman.GitHubDownloader, "get_asset", _refuse)
    monkeypatch.setattr(pkgman, "webdl", _refuse)
    monkeypatch.setattr(pkgman.requests, "get", _refuse)
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path / "addons")
