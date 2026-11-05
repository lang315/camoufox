"""Journey 1: install the package the way a user does, launch in every display
mode, and leave nothing running after close."""

import os
import platform
import subprocess
import textwrap
import time
import venv
from pathlib import Path

import pytest

from oracle.docs import cite
from util import wait_gone

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", [True, False, "virtual"], ids=["headless", "headful", "virtual"])
def test_launch_modes(drv, site, binary, mode, check):
    if mode == "virtual":
        print(cite("virtual"))
        if platform.system() != "Linux":
            pytest.skip("headless='virtual' is documented for Linux only")
    t0 = time.monotonic()
    b = drv.launch(headless=mode)
    page = b.new_context().new_page()
    page.goto(site.url("/login"))
    print(f"{drv.name} headless={mode!r}: launch + first page {time.monotonic() - t0:.1f}s")
    check(page.eval("document.title") == "Sign in", "page title read back")
    if mode == "virtual":
        # The Xvfb root is 1x1: a window sized from it, not from the identity, reads 1x1.
        inner = tuple(page.eval("[innerWidth, innerHeight]"))
        check(inner != (1, 1), f"innerWidth x innerHeight is not the 1x1 display (got {inner})")
        if drv.name == "pkg":
            # The launcher pins the identity's outer window and screen; the browser derives the inner size.
            window = b.b._camoufox_launch_window
            outer, screen = window["outer"], window["screen"]
            if check(None not in (*outer, *screen), f"the launch records an outer window and a screen (got {window})"):
                check(inner[0] == outer[0], f"the real window took the identity's width: inner {inner}, outer {outer}")
                check(0 < inner[1] < outer[1], f"browser chrome takes the height difference: inner {inner}, outer {outer}")
                check(outer[0] <= screen[0] and outer[1] <= screen[1], f"the window fits the screen: outer {outer}, screen {screen}")
    b.close()
    left = wait_gone(binary)
    check(not left, f"no browser process left 15 s after close (left: {left})")
    check.done()


def test_new_context_inner_within_outer(drv, site, check):
    """A NewContext lives in the launch's one real window, so it cannot report an inner size
    beyond the outer one (#164, #190)."""
    b = drv.launch()
    page = b.new_identity_context().new_page()
    page.goto(site.url("/login"))
    inner, outer = (tuple(page.eval(f"[{k}Width, {k}Height]")) for k in ("inner", "outer"))
    check(inner[0] <= outer[0] and inner[1] <= outer[1], f"innerWidth x innerHeight {inner} fits in outerWidth x outerHeight {outer}")
    b.close()
    check.done()


@pytest.mark.timeout(900)
def test_fresh_venv_install(tmp_path, site, binary):
    venv.create(tmp_path / "venv", with_pip=True)
    py = tmp_path / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(REPO / "python")], check=True, timeout=600)
    script = textwrap.dedent(f"""
        from camoufox.sync_api import Camoufox
        with Camoufox(executable_path={str(binary)!r}, headless=True) as browser:
            page = browser.new_page()
            page.goto({site.url("/login")!r})
            print("TITLE=" + page.title())
    """)
    r = subprocess.run([str(py), "-c", script], capture_output=True, text=True, timeout=180)
    assert "TITLE=Sign in" in r.stdout, f"exit {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr[-4000:]}"
