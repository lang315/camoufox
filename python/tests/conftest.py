"""Shared fixtures for the camoufox test suite."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# camoufox computes its cache directories when it is first imported, from the
# platform's cache location (HOME on macOS, XDG_CACHE_HOME on Linux,
# LOCALAPPDATA on Windows). Point all of them at a temp root before that import,
# or the suite reads and writes the developer's real cache (#279).
CACHE_ROOT = Path(tempfile.mkdtemp(prefix="camoufox-pytest-")).resolve()
os.environ["HOME"] = os.environ["USERPROFILE"] = str(CACHE_ROOT)
os.environ["LOCALAPPDATA"] = str(CACHE_ROOT / "AppData" / "Local")
os.environ["XDG_CACHE_HOME"] = str(CACHE_ROOT / ".cache")

from camoufox import pkgman, utils  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE_DIR = Path(pkgman.__file__).resolve().parent


def cache_paths_outside(root: Path) -> list:
    """Every camoufox cache constant that resolves outside `root`.

    A cache constant is a module-level Path in the package that has a
    "camoufox" component and is not the package's own source tree, so a new one
    is covered without being listed here.
    """
    outside = []
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("camoufox") or module is None:
            continue
        for attr, value in vars(module).items():
            if not isinstance(value, Path) or "camoufox" not in value.parts:
                continue
            resolved = value.resolve()
            if not (resolved.is_relative_to(PACKAGE_DIR) or resolved.is_relative_to(root)):
                outside.append(f"{name}.{attr} = {value}")
    return outside


def pytest_sessionstart(session):
    outside = cache_paths_outside(CACHE_ROOT)
    if outside:
        raise pytest.UsageError(
            f"cache paths outside the test root {CACHE_ROOT}: " + "; ".join(outside)
        )


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)


@pytest.fixture
def cache_paths_outside_root():
    return cache_paths_outside


@pytest.fixture(autouse=True)
def empty_cache_root():
    """Each test starts and ends with an empty cache."""
    yield
    for child in CACHE_ROOT.iterdir():
        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()


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
    BaseException, not Exception, so no `except Exception` on the way can
    swallow it (#110).

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

    # Tests that call launch_options() without `executable_path` or
    # `exclude_addons` would otherwise need a managed install and the default
    # addons: read the bundle from the repo and skip the addon lookup, which a
    # build with no bundled uBlock Origin answers with a warning.
    monkeypatch.setattr(utils, "get_path", repo_get_path)
    monkeypatch.setattr(utils, "installed_verstr", lambda: repo_version())
    monkeypatch.setattr(utils, "launch_path", lambda *_a, **_k: "/nonexistent/camoufox")
    monkeypatch.setattr(utils, "add_default_addons", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def no_host_gpu_probe(monkeypatch):
    """launch_options launches the browser to read the host's GPU when an
    identity claims the host's OS. This suite has no browser, and its results
    must not depend on the machine running it, so the host reads as having no
    WebGL. Tests of the probe's consumers patch it themselves."""
    from camoufox import utils

    monkeypatch.setattr(utils, 'host_gpu', lambda *args: None)
