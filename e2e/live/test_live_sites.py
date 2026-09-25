"""Journey 7: real public sites. Never on the PR gate (marker `live`).

Detector pages print an aggregate only: a grade, or a count and a total. This
repository is public, and per-vector detail stays out of it, the same rule
ci/run_sundial.py follows. A network failure is a SKIP, never a PASS or a FAIL.
"""

import re
import time

import pytest

from drivers import make

pytestmark = pytest.mark.live
NETWORK = ("NS_ERROR_UNKNOWN_HOST", "NS_ERROR_NET", "NS_ERROR_CONNECTION_REFUSED", "NS_ERROR_PROXY", "Timeout")


@pytest.fixture
def page(binary):
    d = make("pkg", binary)
    b = d.launch(headless=False)
    yield b.new_context().new_page()
    d.close_all()


def goto(page, url):
    try:
        page.goto(url)
    except Exception as e:
        if any(n in str(e) for n in NETWORK):
            pytest.skip(f"network: {str(e)[:200]}")
        raise


def text(page) -> str:
    try:
        return page.eval("document.body ? document.body.innerText : ''")
    except Exception:  # the challenge or scan navigated mid-read; read again next tick
        return ""


def poll(page, pattern, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        m = re.search(pattern, text(page), re.I)
        if m:
            return m
        time.sleep(1)
    return None


def test_sannysoft(page):
    goto(page, "https://bot.sannysoft.com/")
    time.sleep(5)
    c = page.eval("({passed: document.querySelectorAll('.passed').length, failed: document.querySelectorAll('.failed').length})")
    print(f"sannysoft: {c['passed']} passed / {c['passed'] + c['failed']} total")
    assert c["passed"] + c["failed"] > 0, "the page produced no results"


def test_creepjs(page):
    goto(page, "https://abrahamjuliot.github.io/creepjs/")
    m = poll(page, r"(\d+)% like headless", 30)
    print(f"creepjs: {m.group(0) if m else 'no headless score found'}")
    assert m, "no headless score on the page"


def test_browserscan(page):
    goto(page, "https://www.browserscan.net/")
    m = poll(page, r"authenticity[^0-9]{0,40}(\d+(?:\.\d+)?)\s*%", 40)
    print(f"browserscan: authenticity {m.group(1) + '%' if m else 'not found'}")
    assert m, "no authenticity score on the page"


def test_pixelscan(page):
    goto(page, "https://pixelscan.net/")
    page.click("text=Scan My Browser Now")
    m = poll(page, r"\b(inconsistent|consistent)\b", 40)
    print(f"pixelscan: {m.group(1) if m else 'no verdict found'}")
    assert m, "no verdict on the page"


CLOUDFLARE = "https://www.scrapingcourse.com/cloudflare-challenge"
PASSED_CF = r"You bypassed the Cloudflare challenge"


def test_cloudflare_challenge(page, ref):
    # Cloudflare also judges the IP: a datacenter runner can be refused whatever
    # the browser. Oracle B, bracketed, as for Google below.
    def reference():
        rb = ref.launch(headless=False)
        try:
            p = rb.new_context().new_page()
            goto(p, CLOUDFLARE)
            return bool(poll(p, PASSED_CF, 40))
        finally:
            rb.close()

    before = reference()
    goto(page, CLOUDFLARE)
    ours = bool(poll(page, PASSED_CF, 40))
    after = reference()
    print(f"cloudflare passed: reference-before={before} camoufox={ours} reference-after={after}")
    if not ours and not (before and after):
        pytest.skip("the reference browser did not pass from this IP either")
    assert ours, "Camoufox failed the challenge between two reference passes"


def google_blocked(page) -> bool:
    goto(page, "https://www.google.com/search?q=camoufox+browser")
    time.sleep(3)
    return "/sorry/" in page.eval("location.href") or "unusual traffic" in text(page).lower()


def test_google_search_not_blocked(page, ref):
    # Google also blocks by IP reputation and by query rate, so a lone block says
    # nothing. Oracle B, bracketed: the reference browser queries just before and
    # just after; only a block that neither reference saw counts against Camoufox.
    def reference():
        rb = ref.launch(headless=False)
        try:
            return google_blocked(rb.new_context().new_page())
        finally:
            rb.close()

    before = reference()
    ours = google_blocked(page)
    after = reference()
    print(f"google blocked: reference-before={before} camoufox={ours} reference-after={after}")
    if before or after:
        pytest.skip("Google blocks the reference browser from this IP too")
    assert not ours, "Google blocked Camoufox between two unblocked reference queries"


def test_youtube_loads(page):
    goto(page, "https://www.youtube.com/")
    assert "YouTube" in page.eval("document.title")
