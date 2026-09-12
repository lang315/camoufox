"""Shared fixtures for the camoufox test suite."""

from pathlib import Path

import pytest

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
def no_browser_fetch(monkeypatch):
    """Fail any test that reaches the browser fetcher instead of mocking it.

    Running the suite locally used to download the browser (issue #108). Every
    entry point that ends in a network request raises here, so the offending
    test names itself rather than silently opening a socket to GitHub.

    What this cannot see: the uBlock Origin addon download (addons.py:56) binds
    webdl at import time and catches the refusal at addons.py:94-97, so it is
    printed into captured output rather than failing the test (#110).
    """

    def _refuse(*args, **kwargs):
        raise RuntimeError("test reached the browser fetcher; mock it (#108)")

    monkeypatch.setattr(pkgman.CamoufoxFetcher, "install", _refuse)
    monkeypatch.setattr(pkgman.CamoufoxFetcher, "fetch_latest", _refuse)
    monkeypatch.setattr(pkgman.GitHubDownloader, "get_asset", _refuse)
    monkeypatch.setattr(pkgman, "webdl", _refuse)
    monkeypatch.setattr(pkgman.requests, "get", _refuse)
