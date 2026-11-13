"""
A main-world evaluate resolves no page global the evaluated script does not name.

The page's own global keeps its lazily created standard classes in the order the
page first used them, and Object.getOwnPropertyNames(window) lists them in that
order. The `mw:` wrapper (content/Runtime.js mainWorldEvaluate) named eleven typed
array constructors, NaN and Infinity (which bring Number, isNaN, parseInt...),
Error, Date, URL and Array in the page, and the main world's stringify wrapper
named JSON, Date and Array there, so the first `mw:` evaluate resolved all of
them. Typed arrays and the others are now told by internal class, and the
result is read through Debugger instead of the page's JSON.stringify.

Two tabs load the same page, which reads its own global order once it has
settled; only one gets `mw:() => 1` before that. The names the wrapper used to
resolve must stand in the same order in both. Other names are left out: two
untouched tabs already differ there (XMLHttpRequest, JSON, Location,
DOMRectList: tab setup and timing, not the evaluate).

A third tab gets what a scraper evaluates in the main world: querySelectorAll,
getElementsByTagName, querySelector. The DOM objects that creates (a NodeList,
an HTMLCollection, an HTMLPreElement) defined their interfaces on the window
then, before the page used them, because Juggler's main-world code runs in the
page's realm as Debugger code and was taken for the page's own (NodeList
about 30 names early). It is Juggler's, as
an isolated world's is: those interfaces must stand where the untouched tab has
them. It is compared with an untouched tab opened just before it, not the
first: the first tab of a browser places HTMLCollection differently from every
later one with no evaluate at all (measured 2026-11-04: 415 vs ~944).

Last, the tell of a page's own view with uBlock Origin loaded: in every tab after the first, RegExp
stands right after Number in the global order, as in stock Firefox. uBO 1.76.0 moved it after URL (#447).
The comparisons above leave that out: the first tab is not compared, and the tabs after it shift together.
Stock Firefox, launched on the same page in several tabs, is the control: it must hold one order of those
three names in every tab with RegExp right after Number, else the check is SETUP-INVALID.

    python browser/tests/playwright/patches/main-world-eval-globals.py
"""

import http.server
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from helpers import resolve_binary, stock_firefox, stock_gpu_parity  # noqa: E402

TABS = 4
LAUNCHES = 3
TELL = ("Number", "RegExp", "URL")

PAGE = b"""<!doctype html><title>g</title><pre id="o"></pre><script>
setTimeout(() => {
  const keys = Object.getOwnPropertyNames(window);
  document.getElementById('o').textContent = JSON.stringify({
    order: keys,
    int16: Object.getOwnPropertyNames(Int16Array).join(','),
  });
}, 1500);
</script>"""

# The page's own view, sent to the server so a browser nobody drives can report it too.
ORDER_PAGE = b"""<!doctype html><title>o</title><script>
setTimeout(() => {
  const keys = Object.getOwnPropertyNames(window);
  fetch('/order' + location.search, {method: 'POST', body: JSON.stringify(keys)});
}, 1500);
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(ORDER_PAGE if self.path.startswith("/orders") else PAGE)

    def do_POST(self):
        tab = int(parse_qs(urlparse(self.path).query)["tab"][0])
        self.server.orders[tab] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()


def serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.orders = {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/"


def probe(binary):
    from camoufox.sync_api import Camoufox

    srv, url = serve()
    out = {}
    try:
        with Camoufox(executable_path=str(binary), headless=True, os="linux", main_world_eval=True,
                      i_know_what_im_doing=True) as browser:
            for name in ("plain", "mw", "plain2", "scrape"):
                page = browser.new_page()
                page.goto(url, wait_until="load")
                if name == "mw":
                    page.evaluate("mw:() => 1")
                elif name == "scrape":
                    page.evaluate(SCRAPE)
                out[name] = json.loads(page.locator("#o:not(:empty)").text_content(timeout=10000))
    finally:
        srv.shutdown()
    return out


def wait_for_tabs(srv, count, timeout=60):
    deadline = time.time() + timeout
    while len(srv.orders) < count and time.time() < deadline:
        time.sleep(0.5)
    return dict(srv.orders)


def camoufox_tab_orders(binary):
    """The page's global order in each of TABS tabs of one launch, opened one after the other."""
    from camoufox.sync_api import Camoufox

    srv, url = serve()
    try:
        with Camoufox(executable_path=str(binary), headless=True, os="linux", main_world_eval=True,
                      i_know_what_im_doing=True) as browser:
            for tab in range(TABS):
                browser.new_page().goto(f"{url}orders?tab={tab}", wait_until="load")
                wait_for_tabs(srv, tab + 1)
        return dict(srv.orders)
    finally:
        srv.shutdown()


def stock_tab_orders(stock):
    """The same page in TABS tabs of one stock Firefox, given as arguments, so no driver is involved."""
    spec = importlib.util.spec_from_file_location("getter_cost_parity", HERE / "getter-cost-parity.py")
    parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity)
    srv, url = serve()
    profile, proc, log = parity.run_stock(stock, *[f"{url}orders?tab={tab}" for tab in range(TABS)])
    try:
        return wait_for_tabs(srv, TABS)
    finally:
        stock_gpu_parity().stop_browser(proc, profile)
        Path(log).unlink(missing_ok=True)
        srv.shutdown()


def tell(order):
    """The order of the names the uBO release moved, those the page lists."""
    return [n for n in order if n in TELL]


# What mainWorldEvaluate and its result path could resolve in the page, minus JSON
# (moves between two untouched tabs too).
WATCHED = ("Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array",
           "Float16Array", "Float32Array", "Float64Array", "BigInt64Array", "BigUint64Array", "Number", "NaN",
           "Infinity", "isNaN", "isFinite", "parseInt", "parseFloat", "Error", "Date", "URL", "RegExp", "Array")


# A scraper's main-world read, and the interfaces of what it creates.
SCRAPE = ("mw:() => [document.querySelectorAll('*').length, document.getElementsByTagName('pre').length, "
          "document.querySelector('pre').id, document.title]")
SCRAPED = ("NodeList", "HTMLCollection", "HTMLPreElement")


def watched(order, names=WATCHED):
    return [n for n in order if n in names]


def moved(a, b):
    import difflib
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [b[j1:j2] or a[i1:i2] for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]


def tell_failures(stock, binary):
    """Failures of the RegExp-after-Number check; a control that does not hold is one too."""
    failures = []
    controls = [tell(order) for _ in range(LAUNCHES) for order in stock_tab_orders(stock).values()]
    reference = controls[0] if controls else None
    if (len(controls) != LAUNCHES * TABS or any(c != reference for c in controls)
            or sorted(reference) != sorted(TELL) or reference.index("RegExp") != reference.index("Number") + 1):
        failures.append(f"SETUP-INVALID: stock Firefox does not hold one order of {TELL} with RegExp right "
                        f"after Number in all {LAUNCHES * TABS} tabs: {controls}")
        return failures
    for launch in range(LAUNCHES):
        orders = camoufox_tab_orders(binary)
        if len(orders) != TABS:
            failures.append(f"SETUP-INVALID: launch {launch} reported {len(orders)} of {TABS} tabs")
            continue
        for tab in range(1, TABS):
            if tell(orders[tab]) != reference:
                failures.append(f"launch {launch} tab {tab}: {tell(orders[tab])}, stock {reference} "
                                f"(RegExp at index {orders[tab].index('RegExp')}, URL at {orders[tab].index('URL')})")
    return failures


def main() -> int:
    r = probe(resolve_binary())
    failures = []
    diff = moved(watched(r["plain"]["order"]), watched(r["mw"]["order"]))
    if diff:
        failures.append(f"global order moved by one mw: evaluate: {diff}")
    # Among the standard classes, which stand still between untouched tabs: the untouched tab
    # defines the scraped interfaces only when it enumerates, after them.
    names = WATCHED + SCRAPED
    diff = moved(watched(r["plain2"]["order"], names), watched(r["scrape"]["order"], names))
    if diff:
        failures.append(f"global order moved by a main-world DOM read (the driver's objects defined their "
                        f"interfaces on the window): {diff}")
    if r["plain"]["int16"] != r["mw"]["int16"]:
        failures.append(f"Int16Array own keys {r['mw']['int16']!r}, untouched page {r['plain']['int16']!r}")
    failures += tell_failures(stock_firefox(), resolve_binary())
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"PASS: a mw: evaluate leaves the page's globals as they were ({len(r['mw']['order'])} names)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
