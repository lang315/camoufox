"""Journey 6: ordinary web APIs still work: the same outcome as Playwright's own
Firefox (oracle B). Both run headful: headless Firefox has no GL context."""

import json

import pytest

from oracle.docs import cite
from util import TWO_READS, TWO_READS_GL, reference_verdict, wait_out

# Pixel readback of a launch whose canvas is covered is RFP's random placeholder, so these
# two entries cannot match the reference; the placeholder is asserted instead.
READBACK = ("canvas", "webgl")


GEO = {"latitude": 41.89, "longitude": 12.49}
OTHER_GEO = {"latitude": 35.68, "longitude": 139.69}


def run_geo(driver, site, geo):
    """What the page's own getCurrentPosition gets in a context granted the permission and `geo`."""
    b = driver.launch(headless=False)
    page = b.new_context(permissions=["geolocation"], geolocation=geo, origin=site.url("/").rstrip("/")).new_page()
    page.goto(site.url("/geo"))
    got = wait_out(page, 15)
    b.close()
    return got


def run_apps(driver, site):
    """The page's results, two reads of one canvas and one GL buffer, whether the launch was covered,
    each failed probe's message and the step it had reached, and every probe's milliseconds."""
    b = driver.launch(headless=False)
    page = b.new_context().new_page()
    page.goto(site.url("/apps"))
    page.click("#clip")
    got = wait_out(page, 90)
    reads = {**page.eval(TWO_READS), **page.eval(TWO_READS_GL)}
    errors = page.eval("document.getElementById('out').dataset.errors")
    timings = page.eval("document.getElementById('out').dataset.timings")
    covered = b.canvas_covered
    b.close()
    return got, reads, covered, errors, timings


@pytest.fixture(scope="module")
def reference(ref, site):
    return run_apps(ref, site)


def test_web_apis_behave_like_the_reference(drv, site, reference, check):
    got, reads, covered, errors, timings = run_apps(drv, site)
    want, plain, _, ref_errors, ref_timings = reference
    print(f"probe errors: camoufox={errors} reference={ref_errors}")
    print(f"probe timings: camoufox={timings} reference={ref_timings}")
    for api in sorted(want):
        if not (covered and api in READBACK):
            verdict = reference_verdict(api, got.get(api), want[api], errors, ref_errors)
            if verdict == "reference-invalid":
                check(False, f"REFERENCE INVALID {api}: the reference Firefox ran out of the page's time budget "
                              f"({json.loads(ref_errors)[api]}) while camoufox={got.get(api)!r}; not a Camoufox difference", ledger=False)
            else:
                check(verdict == "same", f"{api}: camoufox={got.get(api)!r} reference={want[api]!r} "
                                         f"(camoufox {json.loads(timings)[api]}, reference {json.loads(ref_timings)[api]})")
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


@pytest.fixture(scope="module")
def reference_geo(ref, site):
    return run_geo(ref, site, GEO)


def test_geolocation_answers_like_the_reference(drv, site, reference_geo, check):
    """Both sides are granted the permission and given the same position, so each answers at once with it.
    Granted nothing, the page's request never completes in either browser and the two would match on
    that (#385); the second launch is the control that shows this comparison can see a difference."""
    print(f"geolocation: reference={reference_geo}")
    got = run_geo(drv, site, GEO)
    check(reference_geo["kind"] == "position", f"the reference Firefox answers with a position: {reference_geo}", ledger=False)
    check(got == reference_geo, f"geolocation: camoufox={got} reference={reference_geo}")
    other = run_geo(drv, site, OTHER_GEO)
    check(other != reference_geo, f"a different position is told from the reference (else VACUOUS): {other}", ledger=False)
    check.done()
