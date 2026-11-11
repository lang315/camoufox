"""
A default launch, uBlock Origin included, keeps Firefox's speculative loading.

uBO's default `prefetchingDisabled: true` (js/background.js:123, uBO 1.76.0) is applied
at startup (js/start.js:197) as `privacy.network.networkPredictionEnabled.set(false)`,
which sets network.prefetch-next=false, network.dns.disablePrefetch=true and
network.http.speculative-parallel-limit=0 (ext-privacy.js, Firefox 159). Stock keeps
true, false, 20, so a page can tell: a `rel=prefetch` request that stock makes never
arrives, and neither does the `rel=preconnect` connection (#427).

The guard waits until uBO has finished starting, then loads a page with both links
and reads what the server hears:

    prefetch   the server receives /prefetch-me.txt
    preconnect the second listener accepts a TCP connection before any request

"uBO has finished starting" is read from uBO itself: it blocks the ad script. The
filter lists are compiled after start.js applies the browser settings (line 195),
and uBO holds page requests until they are, so a blocked ad means the settings are
already applied. A read taken earlier would pass wrongly, because before uBO acts
the prefs are at stock values; the guard fails when uBO never blocks, so a launch
without uBO cannot pass either.

What would pass wrongly anyway: a prefetch or preconnect that Firefox skips for a
reason of its own. Both are measured in stock 159.0 (2 of 2 launches each, #427), the
page is the same, and the control arm requires the page itself to have reached the server.

    python browser/tests/playwright/patches/ubo-speculative-loading.py
"""

import functools
import http.server
import importlib.util
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import check, launch_kwargs  # noqa: E402

# How long a speculative request may take to reach the server once the page has loaded.
SETTLE_S = 15


def frozen():
    """ubo-lists-frozen.py as a module: it owns the recording proxy and the ad page."""
    spec = importlib.util.spec_from_file_location(
        "ubo_lists_frozen", Path(__file__).resolve().parent / "ubo-lists-frozen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counting_listener() -> tuple:
    """A TCP listener that counts accepted connections, used or not."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    count = [0]

    def serve():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            count[0] += 1
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return sock, count


def main() -> int:
    from camoufox.sync_api import Camoufox

    ubo = frozen()
    requested: list = []

    class Site(ubo.Quiet):
        def do_GET(self):
            requested.append(self.path)
            super().do_GET()

    site = tempfile.mkdtemp()
    listener, connections = counting_listener()
    Path(site, "ad.html").write_text(ubo.AD_PAGE, encoding="utf-8")
    Path(site, "prefetch-me.txt").write_text("x", encoding="utf-8")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Site, directory=site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    Path(site, "links.html").write_text(
        '<!doctype html><title>links</title><link rel=prefetch href="/prefetch-me.txt">'
        f'<link rel=preconnect href="http://127.0.0.1:{listener.getsockname()[1]}">', encoding="utf-8")

    hosts: list = []
    proxy = ubo.recording_proxy(hosts)
    try:
        # The recording proxy refuses every CONNECT, as ubo-lists-frozen.py's does: uBO's
        # ad block is observable without a network, and geoip would fail through it.
        with Camoufox(**launch_kwargs(i_know_what_im_doing=True, geoip=False,
                                      proxy={"server": f"http://127.0.0.1:{proxy.getsockname()[1]}"})) as browser:
            page = browser.new_page()
            deadline = time.monotonic() + ubo.READY_S
            while not ubo.blocks_ad(page, f"{base}/ad.html", hosts):
                if time.monotonic() > deadline:
                    print(f"FAIL: uBO did not block {ubo.AD_HOST} within {ubo.READY_S}s -- check is vacuous")
                    return 1
                time.sleep(1)
            requested.clear()
            page.goto(f"{base}/links.html")
            control = requested.count("/links.html")
            deadline = time.monotonic() + SETTLE_S
            while time.monotonic() < deadline and not (
                    "/prefetch-me.txt" in requested and connections[0]):
                time.sleep(0.5)
    finally:
        proxy.close()
        listener.close()
        srv.shutdown()

    failures: list = []
    print("after uBO blocked the ad script:")
    check(failures, "control: the page reached the server itself", control, 1)
    check(failures, "rel=prefetch requested /prefetch-me.txt", requested.count("/prefetch-me.txt"), 1)
    check(failures, "rel=preconnect opened a connection", connections[0] >= 1, True)
    if failures:
        print(f"\nFAIL: {', '.join(failures)}")
        return 1
    print("\nPASS: uBO leaves Firefox's prefetch and preconnect at stock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
