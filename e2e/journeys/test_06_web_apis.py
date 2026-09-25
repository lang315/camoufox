"""Journey 6: ordinary web APIs still work: the same outcome as Playwright's own
Firefox (oracle B). Both run headful: headless Firefox has no GL context."""

import pytest

from util import wait_out


def run_apps(driver, site):
    b = driver.launch(headless=False)
    page = b.new_context().new_page()
    page.goto(site.url("/apps"))
    page.click("#clip")
    got = wait_out(page, 90)
    b.close()
    return got


@pytest.fixture(scope="module")
def reference(ref, site):
    return run_apps(ref, site)


def test_web_apis_behave_like_the_reference(drv, site, reference, check):
    got = run_apps(drv, site)
    for api in sorted(reference):
        check(got.get(api) == reference[api], f"{api}: camoufox={got.get(api)!r} reference={reference[api]!r}")
    # Absolute, with an in-page control: drawn canvas vs a blank one, cleared GL vs its clear colour.
    check(got["canvas"] is True, "canvas draws")
    check(got["webgl"] is True, "WebGL renders")
    check.done()
