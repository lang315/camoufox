"""Journey 3: proxies, geoip and WebRTC, as a user configures them."""

import time

import pytest

from oracle.docs import cite
from util import header, lan_ips, wait_out

GEOIP_IP = "8.8.8.8"
SPOOFED_WEBRTC_IP = "203.0.113.7"  # TEST-NET-3: cannot be anyone's real address
CONTEXT_WEBRTC_IP = "198.51.100.9"  # TEST-NET-2
# Firefox's own media-plugin update check and downloads, the other outside requests a launch makes.
GMP_HOSTS = {"aus5.mozilla.org", "update.googleapis.com", "edgedl.me.gvt1.com", "dl.google.com",
             "ciscobinary.openh264.org"}


def via_proxy(drv, site, proxy):
    try:
        b = drv.launch(os="windows", proxy=proxy.playwright())
    except Exception as e:
        if "socks" in str(e).lower() and "auth" in str(e).lower():
            pytest.skip(f"{drv.name}: SOCKS5 authentication refused by the client: {e}")
        raise
    page = b.new_context().new_page()
    page.goto(f"http://e2e.test:{site.port1}/fp")  # .test resolves only inside the proxy
    fp = wait_out(page)
    b.close()
    return fp


@pytest.mark.parametrize("kind", ["http", "socks5", "socks5-noauth"])
def test_proxy(drv, site, http_proxy, socks_proxy, socks_proxy_noauth, kind, check):
    proxy = {"http": http_proxy, "socks5": socks_proxy, "socks5-noauth": socks_proxy_noauth}[kind]
    fp = via_proxy(drv, site, proxy)
    req = site.seen("/fp")[-1]
    check("e2e.test" in proxy.hosts, f"the {kind} proxy carried the page (hosts seen: {sorted(set(proxy.hosts))})")
    check(fp["main"]["ua"] == header(req, "User-Agent"), "UA through the proxy matches the header that arrived")
    check.done()


def test_a_hanging_filter_list_download_does_not_hold_pages(drv, site, check):
    """#211: uBO holds every page while it loads its filter lists. A de-DE first run
    used to select a regional list that must be downloaded, so a hanging download
    held pages for uBO's 30 s timeout per mirror. While any list download hangs, a
    page must still load."""
    from web.proxy import Proxy

    proxy = Proxy("http", hang_outside=True)
    lists = lambda: [h for h in proxy.hosts if not h.endswith(".test") and h not in GMP_HOSTS]
    try:
        b = drv.launch(os="windows", locale="de-DE", proxy=proxy.playwright())
        page = b.new_context().new_page()
        # Navigate once a list download is in flight; how soon one starts depends on the host.
        deadline = time.monotonic() + 90
        while not lists() and time.monotonic() < deadline:
            time.sleep(0.2)
        in_flight = lists()
        t0 = time.monotonic()
        error = None
        try:
            page.goto(f"http://e2e.test:{site.port1}/login")  # Playwright's own 30 s timeout bounds it
        except Exception as e:
            error = str(e)[:80]
        took = time.monotonic() - t0
        b.close()
    finally:
        proxy.stop()
    check(in_flight, "a filter-list download was held when the page navigated (else VACUOUS)", ledger=False)
    check(error is None and took < 10, f"the page took {took:.1f} s ({error or 'loaded'}) while {in_flight} hung")
    check.done()


def test_geoip_sets_timezone_and_locale(drv, site, check):
    print(cite("geoip"))
    pytest.importorskip("geoip2", reason="camoufox[geoip] is not installed")
    from camoufox.geolocation import get_geolocation
    try:
        geo = get_geolocation(GEOIP_IP)
    except Exception as e:
        pytest.skip(f"geoip database unavailable: {e}")
    b = drv.launch(os="windows", geoip=GEOIP_IP)
    page = b.new_context().new_page()
    page.goto(site.url("/fp"))
    fp = wait_out(page)
    b.close()
    check(fp["tz"]["tz"] == geo.timezone, f"timezone {fp['tz']['tz']!r}; database says {geo.timezone!r}")
    if geo.locale.region:
        check(fp["main"]["language"].endswith(geo.locale.region),
              f"navigator.language {fp['main']['language']!r} is in region {geo.locale.region!r}")
    check.done()


def test_webrtc_does_not_reveal_lan_address(drv, site, stun, check):
    print(cite("webrtc"))
    lan = lan_ips()
    if not lan:
        pytest.skip("this host has no non-loopback IPv4 address to leak")
    b = drv.launch(os="windows", webrtc_ip=SPOOFED_WEBRTC_IP)
    page = b.new_context().new_page()
    page.goto(site.url(f"/webrtc?stun={sorted(lan)[0]}:{stun.port}"))
    got = wait_out(page, 20)
    b.close()
    text = " ".join(got["candidates"]) + got["sdp"]
    check(stun.seen, f"the STUN server was asked (non-vacuous); {len(got['candidates'])} candidates")
    check(not [ip for ip in lan if ip in text], f"no LAN address {sorted(lan)} in candidates or SDP")
    check(SPOOFED_WEBRTC_IP in text, f"the configured WebRTC IP appears: {got['candidates']}")
    check.done()


def test_context_webrtc_ip_overrides_the_launch_one(drv, site, stun, check):
    # The launch-level IP is only a fallback (#163): a context's own IP must still win.
    lan = lan_ips()
    if not lan:
        pytest.skip("this host has no non-loopback IPv4 address to leak")
    b = drv.launch(os="windows", webrtc_ip=SPOOFED_WEBRTC_IP)
    page = b.new_identity_context(webrtc_ip=CONTEXT_WEBRTC_IP).new_page()
    page.goto(site.url(f"/webrtc?stun={sorted(lan)[0]}:{stun.port}"))
    got = wait_out(page, 20)
    b.close()
    text = " ".join(got["candidates"]) + got["sdp"]
    check(stun.seen, f"the STUN server was asked (non-vacuous); {len(got['candidates'])} candidates")
    check(CONTEXT_WEBRTC_IP in text, f"the context's WebRTC IP appears: {got['candidates']}")
    check(SPOOFED_WEBRTC_IP not in text, "the launch-level WebRTC IP does not")
    check.done()


def ice_gathering_behind_a_context_proxy(drv, site, proxy):
    b = drv.launch(os="windows")
    page = b.new_context(proxy=proxy.playwright()).new_page()
    page.goto(f"http://e2e.test:{site.port1}/webrtc")  # .test resolves only inside the proxy
    got = wait_out(page, 20)
    b.close()
    return got


def test_ice_gathering_completes_behind_a_context_proxy(drv, site, http_proxy, check):
    """#181 (upstream #774): behind Playwright's per-context proxy, ICE gathering
    must reach "complete" as it does in Firefox; the page bounds the wait at 8 s."""
    got = ice_gathering_behind_a_context_proxy(drv, site, http_proxy)
    check("e2e.test" in http_proxy.hosts, "the context's proxy carried the page (non-vacuous)", ledger=False)
    check(got["gathering"][-1] == "complete", f"iceGatheringState went {got['gathering']}; candidates {got['candidates']}")
    check.done()


def test_ice_gathering_completes_behind_a_context_proxy_reference(ref, site, http_proxy):
    """Oracle B for the test above: Playwright's own Firefox behind the same proxy."""
    got = ice_gathering_behind_a_context_proxy(ref, site, http_proxy)
    assert got["gathering"][-1] == "complete", f"iceGatheringState went {got['gathering']}"
