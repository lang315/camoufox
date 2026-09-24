"""Journey 8: long sessions, many contexts, and a browser that dies under you."""

import threading
import time
import urllib.request

import psutil
import pytest

from util import browser_procs, rss_mb

pytestmark = pytest.mark.slow
PAGES = ["/login", "/shop", "/upload", "/download", "/fp"]


def fifty_contexts(driver, site):
    b = driver.launch()
    for i in range(50):
        c = b.new_context()
        p = c.new_page()
        asked = len(site.seen("/login"))
        t0 = time.monotonic()
        try:
            p.goto(site.url("/login"))
        except Exception as e:
            # Which side stalled: did the request reach the server, does the server
            # still answer, and does a fresh page in a fresh context get through?
            with urllib.request.urlopen(site.url("/login"), timeout=10) as r:
                server = r.status
            retry = "ok"
            try:
                c2 = b.new_context()
                c2.new_page().goto(site.url("/login"))
            except Exception as e2:
                retry = f"also failed: {str(e2)[:80]}"
            raise AssertionError(
                f"{driver.name} context {i}: goto failed after {time.monotonic() - t0:.1f}s; server received "
                f"{len(site.seen('/login')) - asked} /login request(s); server answers a direct GET with {server}; "
                f"a fresh context: {retry}; threads alive {threading.active_count()}: {e}") from e
        assert p.eval("document.title") == "Sign in", f"context {i}"
        c.close()
    b.close()


def test_fifty_contexts_in_a_row(drv, site):
    fifty_contexts(drv, site)


def test_fifty_contexts_in_a_row_reference(ref, site):
    """Oracle B for the test above: if Playwright's own Firefox stalls too, the
    cause is the environment or this site, not Camoufox."""
    fifty_contexts(ref, site)


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
