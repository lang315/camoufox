"""Journey 5: contexts and browsers keep users apart."""

from oracle.docs import cite
from util import wait_for, wait_out


def sign_in(page, site):
    page.goto(site.url("/login"))
    page.type("#user", "alice")
    page.type("#pass", "s3cret")
    page.click("#go")
    wait_for(page, "location.pathname === '/account'")


def fp_of(page, site):
    page.goto(site.url("/fp"))
    return wait_out(page)


def identity(fp):
    return (fp["canvas"], fp["main"]["ua"], fp["screen"]["w"], fp["screen"]["h"], str(fp.get("webgl")))


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
    a, c = b.new_identity_context(), b.new_identity_context()
    pa = a.new_page()
    fa, fc = fp_of(pa, site), fp_of(c.new_page(), site)
    check(identity(fa) != identity(fc), "the two contexts have different fingerprints")
    check(identity(fp_of(a.new_page(), site)) == identity(fa), "two pages of one context agree")
    b.close()
    check.done()


def test_two_browsers_at_once(drv, site, check):
    b1, b2 = drv.launch(), drv.launch()
    p1, p2 = b1.new_context().new_page(), b2.new_context().new_page()
    sign_in(p1, site)
    p2.goto(site.url("/account"))
    check(p2.eval("location.pathname") == "/login", "the second browser is signed out")
    f1, f2 = fp_of(p1, site), fp_of(p2, site)
    check(identity(f1) != identity(f2), f"two launches differ in fingerprint ({identity(f1)[:2]} vs {identity(f2)[:2]})")
    b1.close()
    b2.close()
    check.done()
