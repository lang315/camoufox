"""Journey 2: what an ordinary page reads agrees with itself and with what the
server received (oracle C), for each OS a user can ask for (oracle A)."""

import pytest

from oracle import coherence
from oracle.docs import cite
from util import wait_out


def measure(drv, site, identity=False, **launch):
    b = drv.launch(**launch)
    page = (b.new_identity_context() if identity else b.new_context()).new_page()
    page.goto(site.url("/fp"))
    fp = wait_out(page)
    req = site.seen("/fp")[-1]
    b.close()
    return fp, req


def report(check, fp, req, os_name):
    for name, ok, detail, red in coherence.evaluate(fp, req, os_name):
        if ok is None:
            print(f"n/a  {name}: {detail}")
            continue
        check(ok, f"{name}: {detail}")
        check(red, f"{name}: its negative control went red (else VACUOUS)")


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_fingerprint_is_coherent(drv, site, os_name, check):
    print(cite("os_option"), cite("webdriver"))
    fp, req = measure(drv, site, os=os_name)
    report(check, fp, req, os_name)
    check.done()


def test_locale_option_reaches_navigator_and_intl(drv, site, check):
    print(cite("locale"))
    fp, req = measure(drv, site, os="windows", locale="de-DE")
    check(fp["main"]["language"] == "de-DE", f"navigator.language={fp['main']['language']!r}")
    check(fp["intl"].startswith("de"), f"Intl locale={fp['intl']!r}")
    report(check, fp, req, "windows")
    check.done()


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_new_context_fingerprint_is_coherent(drv, site, os_name, check):
    print(cite("unique_context"))
    fp, req = measure(drv, site, identity=True, os=os_name)
    report(check, fp, req, os_name)
    check.done()
