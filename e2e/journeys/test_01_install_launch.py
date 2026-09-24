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
    b.close()
    left = wait_gone(binary)
    check(not left, f"no browser process left 15 s after close (left: {left})")
    check.done()


@pytest.mark.timeout(900)
def test_fresh_venv_install(tmp_path, site, binary):
    venv.create(tmp_path / "venv", with_pip=True)
    py = tmp_path / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(REPO / "pythonlib")], check=True, timeout=600)
    script = textwrap.dedent(f"""
        from camoufox.sync_api import Camoufox
        with Camoufox(executable_path={str(binary)!r}, headless=True) as browser:
            page = browser.new_page()
            page.goto({site.url("/login")!r})
            print("TITLE=" + page.title())
    """)
    r = subprocess.run([str(py), "-c", script], capture_output=True, text=True, timeout=180)
    assert "TITLE=Sign in" in r.stdout, f"exit {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr[-4000:]}"
