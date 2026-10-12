"""Journey 6: ordinary web APIs still work: the same outcome as Playwright's own
Firefox (oracle B). Both run headful: headless Firefox has no GL context."""

import pytest

from oracle.docs import cite
from util import TWO_READS, TWO_READS_GL, wait_out

# Pixel readback of a launch whose canvas is covered is RFP's random placeholder, so these
# two entries cannot match the reference; the placeholder is asserted instead.
READBACK = ("canvas", "webgl")


def run_apps(driver, site):
    """The page's results, two reads of one canvas and one GL buffer, and whether the launch was covered."""
    b = driver.launch(headless=False)
    page = b.new_context().new_page()
    page.goto(site.url("/apps"))
    page.click("#clip")
    got = wait_out(page, 90)
    reads = {**page.eval(TWO_READS), **page.eval(TWO_READS_GL)}
    covered = b.canvas_covered
    b.close()
    return got, reads, covered


@pytest.fixture(scope="module")
def reference(ref, site):
    return run_apps(ref, site)


def test_web_apis_behave_like_the_reference(drv, site, reference, check):
    got, reads, covered = run_apps(drv, site)
    want, plain, _ = reference
    for api in sorted(want):
        if not (covered and api in READBACK):
            check(got.get(api) == want[api], f"{api}: camoufox={got.get(api)!r} reference={want[api]!r}")
    # The placeholder replaces pixels, not the context: WebGL exists either way.
    check(got["webgl"] != "no context", "a WebGL context exists")
    if covered:
        print(cite("canvas_placeholder"))
        # The probe is only comparable if an uncovered browser reads the same buffer twice alike.
        for api, same in plain.items():
            check(same is True, f"{api} of the reference Firefox is equal between two reads (else VACUOUS)", ledger=False)
        for api, same in reads.items():
            check(same is False, f"canvas readback is the placeholder: {api} differs between two reads")
    else:
        # Absolute, with an in-page control: drawn canvas vs a blank one, cleared GL vs its clear colour.
        check(got["canvas"] is True, "canvas draws")
        check(got["webgl"] is True, "WebGL renders")
    check.done()
