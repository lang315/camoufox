"""Shared fixtures for the camoufox test suite."""

from pathlib import Path

import pytest

from camoufox import addons
from camoufox import pkgman, utils

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def repo_get_path(file: str) -> str:
    """What a managed install would carry, read from the repo instead.

    Mirrors how `make package-linux` lays out the bundle: properties.json and
    the fontconfig tree via --includes (browser/settings/, browser/bundle/fontconfig), fonts via
    --fonts (browser/bundle/fonts). get_env_vars() resolves the
    Linux fontconfig through get_path too (utils.py:319), and raises when it
    finds no fonts.conf -- browser/settings/ has none.
    """
    head = str(file).replace("\\", "/").split("/")[0]
    if head in ("fontconfig", "fontconfigs", "fonts"):
        return str(REPO_ROOT / "browser" / "bundle" / file)
    return str(REPO_ROOT / "browser" / "settings" / file)


def repo_version() -> str:
    """The Firefox version this tree builds, from browser/upstream.sh."""
    for line in (REPO_ROOT / "browser" / "upstream.sh").read_text().splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("upstream.sh pins no version")


@pytest.fixture(autouse=True)
def no_browser_fetch(request, monkeypatch, tmp_path):
    """Fail any test that reaches the browser fetcher instead of mocking it.

    Running the suite locally used to download the browser (issue #108). Every
    entry point that ends in a network request raises here, so the offending
    test names itself rather than silently opening a socket to GitHub.

    The refusal is raised through pytest.fail(): its exception derives from
    BaseException, not Exception, so it escapes the `except Exception` that
    addons.py:94 wraps around the uBlock Origin download (#110). ADDONS_DIR is
    redirected because, with the refusal escaping, addons.py:96's rmtree no
    longer runs and a trip would leave a directory in the real user cache.

    A test marked `network` downloads on purpose (test_geoip_sources checks
    what each source serves today), so its downloads are let through.
    """

    def _refuse(*args, **kwargs):
        pytest.fail("test reached the browser fetcher; mock it (#108/#110)")

    monkeypatch.setattr(pkgman.CamoufoxFetcher, "install", _refuse)
    monkeypatch.setattr(pkgman.CamoufoxFetcher, "fetch_latest", _refuse)
    monkeypatch.setattr(pkgman.CamoufoxFetcher, "get_asset", _refuse)
    if not request.node.get_closest_marker("network"):
        monkeypatch.setattr(pkgman, "webdl", _refuse)
        monkeypatch.setattr(pkgman.requests, "get", _refuse)
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path / "addons")

    # Tests that call launch_options() without `executable_path` or
    # `exclude_addons` would otherwise need a managed install and the default
    # addons: read the bundle from the repo and skip the addon download.
    monkeypatch.setattr(utils, "get_path", repo_get_path)
    monkeypatch.setattr(utils, "installed_verstr", lambda: repo_version())
    monkeypatch.setattr(utils, "launch_path", lambda *_a, **_k: "/nonexistent/camoufox")
    monkeypatch.setattr(utils, "add_default_addons", lambda addons_list, exclude_list=None: None)


@pytest.fixture(autouse=True)
def no_host_gpu_probe(monkeypatch):
    """launch_options launches the browser to read the host's GPU when an
    identity claims the host's OS. This suite has no browser, and its results
    must not depend on the machine running it, so the host reads as having no
    WebGL. Tests of the probe's consumers patch it themselves."""
    from camoufox import utils

    monkeypatch.setattr(utils, 'host_gpu', lambda *args: None)
