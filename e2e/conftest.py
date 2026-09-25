"""Fixtures for the end-to-end user-journey suite.

Design: docs/superpowers/specs/2026-09-24-e2e-user-journeys-design.md
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import pytest

from util import build_id, find_binary

E2E = Path(__file__).resolve().parent
REPO = E2E.parent
WORK = REPO / ".ci-work" / "e2e"
RELEASE_REPO = "lang315/camoufox"
PLATFORM_ASSET = {("Darwin", "arm64"): "mac.arm64", ("Darwin", "x86_64"): "mac.x86_64",
                  ("Windows", "AMD64"): "win.x86_64", ("Linux", "x86_64"): "lin.x86_64",
                  ("Linux", "aarch64"): "lin.arm64"}


def pytest_addoption(parser):
    g = parser.getgroup("e2e")
    g.addoption("--binary", help="Camoufox executable to test")
    g.addoption("--zip", help="a release or build zip; unpacked and tested")
    g.addoption("--release", help=f"a {RELEASE_REPO} release tag; its zip for this platform is downloaded")
    g.addoption("--drivers", default="pkg,pw,go", help="comma-separated: pkg,pw,go")
    g.addoption("--soak-seconds", type=float, default=600)


def pytest_generate_tests(metafunc):
    if "drv" in metafunc.fixturenames:
        metafunc.parametrize("drv", metafunc.config.getoption("--drivers").split(","), indirect=True)


def _unpack(zp: Path) -> Path:
    dest = WORK / "unpacked" / zp.stem
    if not dest.exists():
        dest.mkdir(parents=True)
        if os.name == "nt":
            zipfile.ZipFile(zp).extractall(dest)
        else:  # keeps the executable bits zipfile would drop
            subprocess.run(["unzip", "-q", "-o", str(zp), "-d", str(dest)], check=True)
    return find_binary(dest)


def _fetch_release(tag: str) -> Path:
    plat = PLATFORM_ASSET[(platform.system(), platform.machine())]
    with urllib.request.urlopen(f"https://api.github.com/repos/{RELEASE_REPO}/releases/tags/{tag}", timeout=30) as r:
        rel = json.load(r)
    asset = next((a for a in rel["assets"] if a["name"].endswith(f"-{plat}.zip")), None)
    if asset is None:
        pytest.exit(f"release {tag} has no {plat} build (it has: {[a['name'] for a in rel['assets']]}); "
                    "test a build run's artifact with --zip instead", 2)
    zp = WORK / "release" / tag / asset["name"]
    zp.parent.mkdir(parents=True, exist_ok=True)
    if not zp.exists():
        for attempt in range(3):
            try:
                urllib.request.urlretrieve(asset["browser_download_url"], zp)
                break
            except OSError:
                if attempt == 2:
                    raise
    digest = hashlib.sha256(zp.read_bytes()).hexdigest()
    if asset.get("digest"):
        assert asset["digest"] == f"sha256:{digest}", f"{asset['name']}: downloaded {digest}, release says {asset['digest']}"
    return zp


@pytest.fixture(scope="session")
def binary(pytestconfig) -> Path:
    zp = None
    if pytestconfig.getoption("--release"):
        zp = _fetch_release(pytestconfig.getoption("--release"))
    elif pytestconfig.getoption("--zip"):
        zp = Path(pytestconfig.getoption("--zip")).resolve()
    if zp:
        path = _unpack(zp)
    else:
        given = pytestconfig.getoption("--binary") or os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
        if not given:
            pytest.exit("no browser: pass --binary, --zip or --release, or set CAMOUFOX_EXECUTABLE_PATH", 2)
        path = Path(given).resolve()
    if not path.exists():
        pytest.exit(f"browser not found: {path}", 2)
    line = f"e2e binary: {path}  BuildID={build_id(path)}  host={platform.system()} {platform.machine()}"
    if zp:
        line += f"  zip={zp.name} sha256={hashlib.sha256(zp.read_bytes()).hexdigest()}"
    pytestconfig.pluginmanager.get_plugin("terminalreporter").write_line(line)
    return path


@pytest.fixture(scope="session")
def stun():
    from web.stun import Stun
    s = Stun()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def site(stun):
    from web.server import Site
    from oracle.docs import font_markers
    s = Site()
    s.stun_port = stun.port
    s.markers = font_markers()
    s.start()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def http_proxy():
    from web.proxy import Proxy
    p = Proxy("http", auth=("e2e", "pw-http"))
    yield p
    p.stop()


@pytest.fixture(scope="session")
def socks_proxy():
    from web.proxy import Proxy
    p = Proxy("socks5", auth=("e2e", "pw-socks"))
    yield p
    p.stop()


@pytest.fixture(scope="session")
def socks_proxy_noauth():
    from web.proxy import Proxy
    p = Proxy("socks5")
    yield p
    p.stop()


@pytest.fixture
def drv(request, binary):
    from drivers import make
    d = make(request.param, binary)
    yield d
    d.close_all()


@pytest.fixture(scope="session")
def ref():
    from drivers.playwright_drivers import RefDriver
    d = RefDriver()
    yield d
    d.close_all()


@pytest.fixture
def check(request):
    from util import Checks
    return Checks(request.node.nodeid)


def pytest_collection_modifyitems(items):
    import known
    for item in items:
        k = known.for_raise(item.nodeid)
        if k:
            issue, exc, strict = k
            item.add_marker(pytest.mark.xfail(raises=exc, strict=strict, reason=f"known finding #{issue}"))


def pytest_sessionfinish(session):
    from drivers.playwright_drivers import stop_playwright
    stop_playwright()
