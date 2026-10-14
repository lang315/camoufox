"""Journey 2: what an ordinary page reads agrees with itself and with what the
server received (oracle C), for each OS a user can ask for (oracle A)."""

import pytest

from oracle import coherence
from oracle.docs import cite
from util import moz_log_env, packaged_locales, prerequisite, wait_out


def measure(drv, site, identity=False, **launch):
    log = "-".join([drv.name, *map(str, launch.values()), *(["identity"] if identity else [])])
    env = moz_log_env(log)
    b = drv.launch(**launch, env=env) if env else drv.launch(**launch)
    page = (b.new_identity_context() if identity else b.new_context()).new_page()
    asked = len(site.seen("/fp-markers.json"))
    page.goto(site.url("/fp"))
    try:
        fp = wait_out(page)
    except TimeoutError as e:
        # The other half of #171's question: did the page's request reach the server?
        got = len(site.seen("/fp-markers.json")) - asked
        raise TimeoutError(f"{e}; the server received {got} /fp-markers.json; MOZ_LOG {log if env else 'off'}") from None
    req = site.seen("/fp")[-1]
    b.close()
    return fp, req


def report(check, fp, req, os_name, skip=()):
    for name, ok, detail, red in coherence.evaluate(fp, req, os_name):
        if name in skip:
            continue
        if ok is None:
            print(f"n/a  {name}: {detail}")
            continue
        check(ok, f"{name}: {detail}")
        check(red, f"{name}: its negative control went red (else VACUOUS)", ledger=False)


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_fingerprint_is_coherent(drv, site, os_name, check):
    print(cite("os_option"), cite("webdriver"))
    fp, req = measure(drv, site, os=os_name)
    report(check, fp, req, os_name)
    check.done()


def test_locale_option_reaches_navigator_and_intl(drv, site, binary, check):
    print(cite("locale"))
    fp, req = measure(drv, site, os="windows", locale="de-DE")
    check(fp["main"]["language"] == "de-DE", f"navigator.language={fp['main']['language']!r}")
    # Intl follows the app locale, which Gecko negotiates against the PACKAGED locales
    # (intl.locale.requested): a binary that does not package "de" answers en-US.
    packaged = packaged_locales(binary)
    intl = prerequisite(
        "packaged-locales",
        packaged is None or any(p.split("-")[0] == "de" for p in packaged),
        f"the binary packages {packaged}, not de",
    )
    if intl:
        check(fp["intl"].startswith("de"), f"Intl locale={fp['intl']!r}")
    report(check, fp, req, "windows", skip=() if intl else ("intl_locale_matches_language",))
    check.done()


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_new_context_fingerprint_is_coherent(drv, site, os_name, check):
    print(cite("unique_context"))
    fp, req = measure(drv, site, identity=True, os=os_name)
    report(check, fp, req, os_name)
    check.done()
