"""Journey 6: ordinary web APIs still work: the same outcome as Playwright's own
Firefox (oracle B). Both run headful: headless Firefox has no GL context."""

import json

import pytest

from oracle.docs import cite
from util import TWO_READS, TWO_READS_GL, reference_verdict, wait_out

# Pixel readback of a launch whose canvas is covered is RFP's random placeholder, so these
# two entries cannot match the reference; the placeholder is asserted instead.
READBACK = ("canvas", "webgl")


def run_apps(driver, site):
    """The page's results, two reads of one canvas and one GL buffer, whether the launch was covered,
    and each failed probe's message and the step it had reached."""
    b = driver.launch(headless=False)
    page = b.new_context().new_page()
    page.goto(site.url("/apps"))
    page.click("#clip")
    got = wait_out(page, 90)
    reads = {**page.eval(TWO_READS), **page.eval(TWO_READS_GL)}
    errors = page.eval("document.getElementById('out').dataset.errors")
    covered = b.canvas_covered
    b.close()
    return got, reads, covered, errors


@pytest.fixture(scope="module")
def reference(ref, site):
    return run_apps(ref, site)


def test_web_apis_behave_like_the_reference(drv, site, reference, check):
    got, reads, covered, errors = run_apps(drv, site)
    want, plain, _, ref_errors = reference
    print(f"probe errors: camoufox={errors} reference={ref_errors}")
    for api in sorted(want):
        if not (covered and api in READBACK):
            verdict = reference_verdict(api, got.get(api), want[api], errors, ref_errors)
            if verdict == "reference-invalid":
                check(False, f"REFERENCE INVALID {api}: the reference Firefox ran out of the page's time budget "
                              f"({json.loads(ref_errors)[api]}) while camoufox={got.get(api)!r}; not a Camoufox difference", ledger=False)
            else:
                check(verdict == "same", f"{api}: camoufox={got.get(api)!r} reference={want[api]!r}")
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
