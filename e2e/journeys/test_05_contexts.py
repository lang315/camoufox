"""Journey 5: contexts and browsers keep users apart."""

import platform

from oracle.docs import cite
from util import TWO_READS, wait_for, wait_out


def sign_in(page, site):
    page.goto(site.url("/login"))
    page.type("#user", "alice")
    page.type("#pass", "s3cret")
    page.click("#go")
    wait_for(page, "location.pathname === '/account'")


def fp_of(page, site):
    page.goto(site.url("/fp"))
    return wait_out(page)


CONTEXTS = 8


def identity(fp, covered=False):
    # A covered launch reads RFP's random placeholder, which never agrees with itself and
    # differs from every other read: it can say neither "same" nor "different". Audio renders
    # as stock Firefox does on every context, so it is not part of an identity.
    canvas = () if covered else (fp["canvas"],)
    return (*canvas, fp["main"]["ua"], fp["screen"]["w"], fp["screen"]["h"], str(fp.get("webgl")))


def test_two_contexts_share_nothing(drv, site, check):
    b = drv.launch(os="windows")
    a, c = b.new_context(), b.new_context()
    pa, pc = a.new_page(), c.new_page()
    sign_in(pa, site)
    pa.eval("localStorage.setItem('owner', 'A')")
    pc.goto(site.url("/account"))
    check(pc.eval("location.pathname") == "/login", "the second context is signed out")
    check(pc.eval("localStorage.getItem('owner')") is None, "localStorage is not shared")
    check(not [k for k in c.cookies() if k["name"] == "session"], "no session cookie in the second context")
    b.close()
    check.done()


def test_new_context_gives_each_context_its_own_identity(drv, site, check):
    print(cite("unique_context"))
    b = drv.launch(os="windows")
    contexts = [b.new_identity_context() for _ in range(CONTEXTS)]
    a = contexts[0]
    fa = fp_of(a.new_page(), site)
    seen = {identity(fa, b.canvas_covered)} | {identity(fp_of(c.new_page(), site), b.canvas_covered) for c in contexts[1:]}
    covered = b.canvas_covered
    # Nothing a page reads differs between two contexts by construction any more: an identity draws
    # its UA, screen and GPU from recorded distributions, so two draws can agree. All of CONTEXTS
    # agreeing is what a context that kept the launch's identity would show.
    check(len(seen) > 1, f"{CONTEXTS} contexts did not all present one fingerprint ({len(seen)} distinct)")
    check(identity(fp_of(a.new_page(), site), covered) == identity(fa, covered), "two pages of one context agree")
    b.close()
    check.done()


def test_two_browsers_at_once(drv, site, check):
    # Two OSes, so the user agents differ by construction.
    b1, b2 = drv.launch(os="windows"), drv.launch(os="macos")
    p1, p2 = b1.new_context().new_page(), b2.new_context().new_page()
    sign_in(p1, site)
    p2.goto(site.url("/account"))
    check(p2.eval("location.pathname") == "/login", "the second browser is signed out")
    f1, f2 = fp_of(p1, site), fp_of(p2, site)
    covered = b1.canvas_covered or b2.canvas_covered
    check(identity(f1, covered) != identity(f2, covered),
          f"two launches differ in fingerprint ({identity(f1, covered)[:2]} vs {identity(f2, covered)[:2]})")
    b1.close()
    b2.close()
    check.done()


def two_reads(browser, site):
    page = browser.new_context().new_page()
    page.goto(site.url("/"))
    return page.eval(TWO_READS)


def test_a_covered_launch_reads_the_canvas_placeholder(drv, ref, site, check):
    print(cite("canvas_placeholder"))
    # Not the host's OS, so the launch is covered whatever GPU the host has.
    b = drv.launch(os="linux" if platform.system() == "Windows" else "windows")
    got, plain = two_reads(b, site), two_reads(ref.launch(), site)
    # The probe is only comparable if an uncovered browser reads the same canvas twice alike.
    for api, same in plain.items():
        check(same, f"{api} of the reference Firefox is equal between two reads (else VACUOUS)", ledger=False)
    for api, same in got.items():
        check(not same, f"canvas readback is the placeholder: {api} differs between two reads")
    b.close()
    check.done()
