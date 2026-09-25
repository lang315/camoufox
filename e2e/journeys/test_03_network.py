"""Journey 3: proxies, geoip and WebRTC, as a user configures them."""

import pytest

from oracle.docs import cite
from util import header, lan_ips, wait_out

GEOIP_IP = "8.8.8.8"
SPOOFED_WEBRTC_IP = "203.0.113.7"  # TEST-NET-3: cannot be anyone's real address


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
