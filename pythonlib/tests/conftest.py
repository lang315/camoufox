"""Shared fixtures for the camoufox test suite."""

import pytest

from camoufox import pkgman


@pytest.fixture(autouse=True)
def no_browser_fetch(monkeypatch):
    """Fail any test that reaches the browser fetcher instead of mocking it.

    Running the suite locally used to download the browser (issue #108). Every
    entry point that ends in a network request raises here, so the offending
    test names itself rather than silently opening a socket to GitHub.
    """

    def _refuse(*args, **kwargs):
        raise RuntimeError("test reached the browser fetcher; mock it (#108)")

    monkeypatch.setattr(pkgman.CamoufoxFetcher, "install", _refuse)
    monkeypatch.setattr(pkgman.CamoufoxFetcher, "fetch_latest", _refuse)
    monkeypatch.setattr(pkgman.GitHubDownloader, "get_asset", _refuse)
    monkeypatch.setattr(pkgman, "webdl", _refuse)
    monkeypatch.setattr(pkgman.requests, "get", _refuse)
