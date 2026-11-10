"""
A driver's click on a point an open chrome popup covers goes to the popup at once, as an OS click does.

The parent hands a mouse event inside a visible popup (the date picker a
page's showPicker() opened, a permission doorhanger) to that popup, so it
never reaches the renderer. Juggler waited 5 s per event for a renderer ack
that could not come: a click under the picker took 15 s and timed out
Playwright, and every input after it queued behind. Stock 158.0.1 Linux, by
OS (XTest) clicks on the same page: the clicks land on the picker at once, the
page sees none of them, the picker stays open. MouseDispatch._popupAt now
sends such an event without waiting for an ack.

The click waits for the condition MouseDispatch._popupAt tests, not for a time:
showPicker() returns in the page when the parent has only been asked to open the
picker, and the clicks go to the page unless the panel has reached state "open" in
the parent by then. The guard reads that state through Marionette's chrome context
and reports how long the panel took.

Runs headless and, where Xvfb is installed, on a private Xvfb display.

    python browser/tests/playwright/patches/popup-covered-click.py
"""

import http.server
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, marionette_args, marionette_env, resolve_binary  # noqa: E402

# A private Xvfb display, started as playwright-window-size.py starts one.
_spec = importlib.util.spec_from_file_location(
    "playwright_window_size", Path(__file__).resolve().parent / "playwright-window-size.py")
_window_size = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_window_size)
xvfb = _window_size.xvfb

# The picker opens under a date input in the page's top-left corner and covers #t.
PAGE = """<!doctype html><html><body style="margin:0">
<button id="open" style="position:absolute;left:600px;top:400px;width:200px;height:40px">open</button>
<div id="t" style="position:absolute;left:60px;top:40px;width:200px;height:100px;background:#ccc">t</div>
<pre id="log" style="position:absolute;left:600px;top:500px"></pre>
<script>
const log = (m) => document.getElementById('log').append(m + ' ');
for (const k of ['mousedown', 'mouseup', 'click']) document.getElementById('t').addEventListener(k, () => log(k));
document.getElementById('open').addEventListener('click', () => {
  const d = document.createElement('input');
  d.type = 'date';
  document.body.prepend(d);
  try { d.showPicker(); log('picker'); document.getElementById('log').dataset.at = Date.now(); }
  catch (e) { log('picker ' + e.name); }
});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE.encode())


# What _popupAt looks for: an open popup that takes mouse events.
POPUPS = """return [...document.querySelectorAll('panel, menupopup, tooltip')].map(
  p => p.state === 'open' && getComputedStyle(p).pointerEvents === 'none' ? 'open, transparent to the mouse' : p.state);"""
OPEN_TIMEOUT_S = 10


def wait_for_open_popup(marionette, picked_at_ms):
    """Wait until a popup is open in the parent. Returns (ms since the page logged 'picker', None),
    or (None, the states of the popups last seen) when none opened in OPEN_TIMEOUT_S."""
    deadline = time.monotonic() + OPEN_TIMEOUT_S
    states = []
    while time.monotonic() < deadline:
        states = marionette.js(POPUPS)
        if "open" in states:
            return round(time.time() * 1000 - picked_at_ms), None
        time.sleep(0.02)
    return None, states


def probe(binary, display):
    from camoufox.sync_api import Camoufox

    port = free_port()
    kw = dict(executable_path=str(binary), headless=display is None, os="linux", i_know_what_im_doing=True,
              args=marionette_args(), env={**marionette_env(), **({"DISPLAY": display} if display else {})},
              firefox_user_prefs={"marionette.port": port})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with Camoufox(**kw) as browser:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{srv.server_port}/", wait_until="load")
        page.locator("#open").click()
        # The page's own log, read from the DOM: evaluate runs in an isolated world.
        picked_at = page.locator("#log").get_attribute("data-at")
        marionette = Marionette(port)
        try:
            open_ms, states = wait_for_open_popup(marionette, float(picked_at or 0))
        finally:
            marionette.close()
        took = []
        for _ in range(2):
            t = time.monotonic()
            try:
                page.locator("#t").click(timeout=4000)
                took.append(round(time.monotonic() - t, 2))
            except Exception as e:
                took.append(type(e).__name__)
            page.wait_for_timeout(300)
        out = {"took": took, "page": page.locator("#log").text_content().split(), "open_ms": open_ms, "states": states}
    srv.shutdown()
    return out


def main() -> int:
    binary = resolve_binary()
    failures, seen = [], {}
    proc, display = xvfb()
    try:
        for where in ("headless", display):
            if where is None:
                continue
            got = probe(binary, None if where == "headless" else where)
            seen[where] = got
            if got["page"][:1] != ["picker"]:
                failures.append(f"{where}: the picker did not open: {got['page']}")
            elif got["open_ms"] is None:
                failures.append(f"{where}: no popup reached state open in {OPEN_TIMEOUT_S} s; popups last seen: {got['states']}")
            elif any(e in got["page"] for e in ("mousedown", "mouseup", "click")):
                failures.append(f"{where}: the page got the clicks, so no popup covered #t: {got['page']}")
            elif not all(isinstance(s, float) and s < 2 for s in got["took"]):
                failures.append(f"{where}: clicks under the picker took {got['took']}, want each under 2 s")
    finally:
        if proc:
            proc.kill()
            proc.wait()
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"PASS: clicks under an open popup go to it at once: {seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
