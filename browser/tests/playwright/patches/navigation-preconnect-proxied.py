"""
A navigation's preconnect and a document's DNS prefetch obey the proxy and routes.

Page.navigate preconnects to the host before the content process asks, as
stock's own loads do. That connection is opened outside the page's load, so it
must take the same path the load does: through a Juggler proxy when the context
has one, and nowhere at all when the caller's route answers the request. A
connection around the proxy shows the exit's server the machine's real address.

The origin listens on this host's own address, which is not loopback (Firefox
never proxies loopback), so a connection reaching it went around the proxy.

What PASS means:
    * direct, the origin is reached: the address works, so silence means something;
    * behind a context proxy and a launch proxy, the proxy serves the page and
      the origin hears nothing;
    * with a route fulfilling the request, the origin hears nothing;
    * a dns-prefetch link in a document that loaded nothing through the proxy
      resolves the name on this machine only when no proxy is in play, which
      the resolver's log shows.

The guard launches without uBlock Origin. uBO's default `prefetchingDisabled` turns Firefox's prefetching
off (network.dns.disablePrefetch) at some moment after startup (js/start.js, uBO 1.76.0), so with it loaded the
direct link resolves in some launches and never in others (Windows, diag-56: 3 of 8 resolved, and the pref read
true by the end of every launch), and the proxied arms would pass whatever the browser did.

The direct link must show up in the log, and the guard waits for it instead of for a
fixed time (a loaded Windows runner took longer than the second the guard once gave it). The
two proxied launches then wait max(1 s, 3 x that latency) for a name that must not appear.
shortcut: Firefox's HTMLDNSPrefetch has no skip log line to wait for (read in mainline, not the 159 tree), so
the negative wait is a calibration: the context arm shares the direct arm's launch, but the launch-proxy arm's
wait comes from another launch, so it is not a proof that the name would have shown in time.

    python browser/tests/playwright/patches/navigation-preconnect-proxied.py
"""

import http.server
import os
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import default_route_ipv4, resolve_binary  # noqa: E402

from camoufox import DefaultAddons  # noqa: E402

PAGE = b"<!doctype html><title>page</title>"
# Long enough for a preconnect behind a finished load to reach the listener.
SETTLE_SECONDS = 1
# How long the direct dns-prefetch link may take to reach the resolver's log before the guard gives up.
RESOLVE_LIMIT_SECONDS = 30


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args) -> None:
        pass


class Listener(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Serves the page and counts every TCP connection, used or not."""

    daemon_threads = True

    def __init__(self, host: str) -> None:
        super().__init__((host, 0), Page)
        self.connections = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def get_request(self):
        accepted = super().get_request()
        self.connections += 1
        return accepted


def connections_during(listener: Listener, action) -> int:
    before = listener.connections
    action()
    time.sleep(SETTLE_SECONDS)
    return listener.connections - before


def prefetch_from(context, name: str, settle: float) -> None:
    """Open a route-fulfilled document, so no load shows Firefox the proxy."""
    page = context.new_page()
    body = f'<!doctype html><link rel="dns-prefetch" href="//{name}">'
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=body))
    page.goto("http://document.test/")
    time.sleep(settle)


def resolver_log(directory: Path) -> str:
    return "".join(path.read_text(encoding="utf-8", errors="replace") for path in directory.iterdir())


def seconds_until_resolved(directory: Path, name: str) -> Optional[float]:
    """How long after now the resolver's log names `name`; None if it never does within the limit."""
    start = time.monotonic()
    while time.monotonic() - start < RESOLVE_LIMIT_SECONDS:
        if name in resolver_log(directory):
            return time.monotonic() - start
        time.sleep(0.1)
    return None


def main() -> int:
    from camoufox.sync_api import Camoufox

    origin = Listener(default_route_ipv4())
    proxy = Listener("127.0.0.1")
    url = f"http://{origin.server_address[0]}:{origin.server_address[1]}/"
    server = f"http://127.0.0.1:{proxy.server_address[1]}"
    log_holder = tempfile.TemporaryDirectory()
    env = {**os.environ, "MOZ_LOG": "sync,append,nsHostResolver:5", "MOZ_LOG_FILE": str(Path(log_holder.name) / "resolver")}
    launch = dict(headless=True, os="linux", executable_path=str(resolve_binary()), i_know_what_im_doing=True, env=env,
                  exclude_addons=[DefaultAddons.UBO])

    log_dir = Path(log_holder.name)
    with Camoufox(**launch) as browser:
        # First: a proxied context turns prefetch off for the whole browser.
        prefetch_from(browser.new_context(), "direct-prefetch.test", 0)
        latency = seconds_until_resolved(log_dir, "direct-prefetch.test")
        settle = max(SETTLE_SECONDS, 3 * latency) if latency is not None else SETTLE_SECONDS
        prefetch_from(browser.new_context(proxy={"server": server}), "context-prefetch.test", settle)
    with Camoufox(**launch, proxy={"server": server}, geoip=False) as browser:
        prefetch_from(browser.new_context(), "launch-prefetch.test", settle)
    resolved = resolver_log(log_dir)
    log_holder.cleanup()

    with Camoufox(**launch) as browser:
        direct = connections_during(origin, lambda: browser.new_page().goto(url))
        served_before = proxy.connections
        around_context = connections_during(
            origin, lambda: browser.new_context(proxy={"server": server}).new_page().goto(url))
        served_context = proxy.connections - served_before

        routed_page = browser.new_page()
        routed_page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=PAGE))
        around_route = connections_during(origin, lambda: routed_page.goto(url))

    with Camoufox(**launch, proxy={"server": server}, geoip=False) as browser:
        served_before = proxy.connections
        around_launch = connections_during(origin, lambda: browser.new_page().goto(url))
        served_launch = proxy.connections - served_before

    checks = [
        ("direct: the origin is reached", direct >= 1, direct),
        ("context proxy: the proxy serves the page", served_context >= 1, served_context),
        ("context proxy: nothing went around it", around_context == 0, around_context),
        ("launch proxy: the proxy serves the page", served_launch >= 1, served_launch),
        ("launch proxy: nothing went around it", around_launch == 0, around_launch),
        ("a route answers the request: the origin hears nothing", around_route == 0, around_route),
        ("direct: a dns-prefetch link is resolved (the two below mean nothing without it)",
         latency is not None, f"after {latency:.1f} s" if latency is not None else f"never resolved in {RESOLVE_LIMIT_SECONDS} s"),
        ("context proxy: a dns-prefetch link is not resolved here", "context-prefetch.test" not in resolved, ""),
        ("launch proxy: a dns-prefetch link is not resolved here", "launch-prefetch.test" not in resolved, ""),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
