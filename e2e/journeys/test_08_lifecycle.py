"""Journey 8: long sessions, many contexts, and a browser that dies under you."""

import time

import psutil
import pytest

from util import browser_procs, rss_mb

pytestmark = pytest.mark.slow
PAGES = ["/login", "/shop", "/upload", "/download", "/fp"]


def test_fifty_contexts_in_a_row(drv, site):
    b = drv.launch()
    for i in range(50):
        c = b.new_context()
        p = c.new_page()
        p.goto(site.url("/login"))
        assert p.eval("document.title") == "Sign in", f"context {i}"
        c.close()
    b.close()


@pytest.mark.timeout(0)
def test_soak(drv, site, binary, pytestconfig):
    seconds = pytestconfig.getoption("--soak-seconds")
    b = drv.launch()
    p = b.new_context().new_page()
    t0, n, rss = time.monotonic(), 0, []
    while time.monotonic() - t0 < seconds:
        for path in PAGES:
            p.goto(site.url(path))
            n += 1
        if n % 50 == 0:
            rss.append(rss_mb(binary))
    assert p.eval("document.title"), "the page still answers at the end"
    print(f"soak {drv.name}: {n} navigations in {seconds:.0f}s; browser RSS MB over time {rss}")
    b.close()


def test_killed_browser_then_relaunch(drv, site, binary):
    b = drv.launch()
    p = b.new_context().new_page()
    p.goto(site.url("/login"))
    procs = browser_procs(binary)
    assert procs, "control: found the running browser's processes"
    for proc in procs:
        try:
            proc.kill()
        except psutil.Error:
            pass
    with pytest.raises(Exception):
        p.goto(site.url("/shop"))
    b2 = drv.launch()
    p2 = b2.new_context().new_page()
    p2.goto(site.url("/login"))
    assert p2.eval("document.title") == "Sign in", "a fresh launch works after the crash"
    b2.close()
