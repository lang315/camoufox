"""Journey 2: what an ordinary page reads agrees with itself and with what the
server received (oracle C), for each OS a user can ask for (oracle A)."""

import platform

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


# One string measured with a serif and with a monospace fallback: a family that resolves
# measures the same under both, a name that does not exist cannot.
SYSTEM_UI_WIDTHS = """(() => {
  const w = (stack) => {
    const s = document.createElement("span");
    s.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;font-size:32px;font-family:" + stack;
    s.textContent = "Hamburgefonstiv 0123456789";
    document.body.appendChild(s);
    const r = s.getBoundingClientRect().width;
    s.remove();
    return r;
  };
  const both = (f) => ({serif: w(f + ",serif"), mono: w(f + ",monospace")});
  return {systemUi: both("system-ui"), appleSystem: both("-apple-system"), absent: both('"No Such Family 263"')};
})()"""


def test_system_ui_resolves_to_the_system_font_of_a_mac(drv, site, check):
    """A macOS identity on a Mac is native: system-ui is the face -apple-system is.
    Stock Firefox 158.0 on a Mac measures both at 431 px (#263: the launch font mask
    refused the hidden family system-ui names there, so it fell to the default serif)."""
    if platform.system() != "Darwin":
        pytest.skip("a native macOS identity needs a macOS host")
    b = drv.launch(os="macos")
    page = b.new_context().new_page()
    page.goto(site.url("/"))
    w = page.eval(SYSTEM_UI_WIDTHS)
    print(f"widths (serif fallback, monospace fallback): {w}")
    check(w["absent"]["serif"] != w["absent"]["mono"], "a family that does not exist measures differently under the two fallbacks (else VACUOUS)", ledger=False)
    check(w["systemUi"]["serif"] == w["systemUi"]["mono"], f"system-ui resolves to a family: {w['systemUi']}")
    check(w["systemUi"]["serif"] == w["appleSystem"]["serif"], f"system-ui is the face -apple-system is: {w['systemUi']['serif']} vs {w['appleSystem']['serif']}")
    b.close()
    check.done()
