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

A click right after showPicker() lands on the picker or the page, whichever the
parent routes it to; either way it must not wait out the ack deadline. The covered
clicks go to a point inside the picker's own rect, read from the browser: the panel
is not always under #t (a window flush right on the headless screen has it pushed
left of its input by the screen's 1366 px edge, #469). A move that Juggler never
delivered waits out its 5 s ack deadline and is a failure of its own, not a covered move.

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

# The picker opens under a date input in the page's top-left corner.
PAGE = """<!doctype html><html><body style="margin:0">
<button id="open" style="position:absolute;left:600px;top:400px;width:200px;height:40px">open</button>
<div id="t" style="position:absolute;left:60px;top:40px;width:200px;height:100px;background:#ccc">t</div>
<pre id="log" style="position:absolute;left:600px;top:500px"></pre>
<script>
const log = (m) => document.getElementById('log').append(m + ' ');
for (const k of ['mousedown', 'mouseup', 'click'])
  document.addEventListener(k, (e) => { if (e.target.id !== 'open') log(k); }, true);
document.addEventListener('mousemove', (e) => { document.documentElement.dataset.moved = e.clientX + ',' + e.clientY; }, true);
document.getElementById('open').addEventListener('click', () => {
  const d = document.createElement('input');
  d.type = 'date';
  document.body.prepend(d);
  try { d.showPicker(); log('picker'); } catch (e) { log('picker ' + e.name); }
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


def timed_click(page):
    t = time.monotonic()
    try:
        page.locator("#t").click(timeout=4000)
        return round(time.monotonic() - t, 2)
    except Exception as e:
        return type(e).__name__


# A covered event is sent without waiting for an ack, so it returns at once.
IMMEDIATE_S = 2
# Pixels from the panel's top to its weekday names row (its date picker, 274 x 303).
WEEKDAY_ROW = 66

# The date picker's panel and the page's content area, in screen pixels (x, y, width, height).
PANEL = """
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  const panel = w.document.getElementById("DateTimePickerPanel");
  if (!panel || panel.state === "closed") continue;
  const b = w.gBrowser.selectedBrowser.getBoundingClientRect();
  const r = panel.getOuterScreenRect();
  return {state: panel.state, panel: [r.left, r.top, r.width, r.height],
          content: [w.mozInnerScreenX + b.x, w.mozInnerScreenY + b.y, b.width, b.height]};
}
return null;
"""


def covered_point(panel, content):
    """A point of the page, relative to its content area, that the panel covers; None if it covers none.
    The row is the picker's weekday names, where a click selects nothing and so leaves the picker open."""
    x0, y0 = max(panel[0], content[0]), max(panel[1], content[1])
    x1 = min(panel[0] + panel[2], content[0] + content[2])
    y1 = min(panel[1] + panel[3], content[1] + content[3])
    if x0 >= x1 or y0 >= y1:
        return None
    y = min(max(panel[1] + WEEKDAY_ROW, y0), y1 - 1)
    return (x0 + x1) // 2 - content[0], y - content[1]


def move_verdict(took_s, page_saw):
    """What a move to a point the picker covers came to."""
    if took_s >= IMMEDIATE_S:
        return "dropped"
    return "reached the page" if page_saw else "covered"


def picker_ready(seen):
    """Whether the picker takes mouse events: open and sized, which is what _popupAt tests."""
    return bool(seen and seen["state"] == "open" and seen["panel"][2] and seen["panel"][3])


def wait_open(m, deadline_s=10):
    """The picker's state and rects once it takes mouse events, else the last state seen."""
    end = time.monotonic() + deadline_s
    seen = None
    while time.monotonic() < end:
        seen = m.js(PANEL)
        if picker_ready(seen):
            return seen
        time.sleep(0.02)
    return seen


def probe(binary, display):
    from camoufox.sync_api import Camoufox

    port = free_port()
    kw = dict(executable_path=str(binary), headless=display is None, os="linux", i_know_what_im_doing=True,
              args=marionette_args(), firefox_user_prefs={"marionette.port": port},
              env={**marionette_env(), **({"DISPLAY": display} if display else {})})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    with Camoufox(**kw) as browser:
        # Each phase has its own page, so its own window and picker panel: a
        # panel still hiding the last picker refuses to open again
        # (nsXULPopupManager::MayShowPopup).
        page = browser.new_page()
        page.goto(url, wait_until="load")
        # A click while the picker opens lands on the picker or the page, as an
        # OS click would, but never waits for an ack the popup swallowed.
        page.locator("#open").click()
        racing = timed_click(page)
        page.close()
        page = browser.new_page()
        page.goto(url, wait_until="load")
        # Connected once this page's window exists: Marionette follows the window it first sees.
        m = Marionette(port)
        try:
            page.locator("#open").click()
            opened = wait_open(m)
        finally:
            m.close()
        out = {"racing": racing, "opened": opened}
        if picker_ready(opened):
            out["point"] = covered_point(opened["panel"], opened["content"])
        if out.get("point"):
            x, y = out["point"]
            t = time.monotonic()
            page.mouse.move(x, y)
            took = round(time.monotonic() - t, 2)
            saw = page.evaluate("""([x, y]) => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(
                () => r(document.documentElement.dataset.moved === `${x},${y}`))))""", [x, y])
            out["move"] = (move_verdict(took, saw), took)
            out["took"] = []
            for _ in range(2):
                t = time.monotonic()
                try:
                    page.mouse.click(x, y)
                    out["took"].append(round(time.monotonic() - t, 2))
                except Exception as e:
                    out["took"].append(type(e).__name__)
                page.wait_for_timeout(300)
        # The page's own log, read from the DOM: evaluate runs in an isolated world.
        out["page"] = page.locator("#log").text_content().split()
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
            opened = got["opened"]
            if not isinstance(got["racing"], float) or got["racing"] >= IMMEDIATE_S:
                failures.append(f"{where}: a click while the picker opened took {got['racing']}, want under {IMMEDIATE_S} s")
            if not picker_ready(opened) or got["page"][:1] != ["picker"]:
                failures.append(f"{where}: the picker did not open: {opened}, page log {got['page']}")
                continue
            if not got["point"]:
                failures.append(f"{where}: the picker {opened['panel']} covers none of the page {opened['content']}")
                continue
            verdict, took = got["move"]
            if verdict == "dropped":
                failures.append(f"{where}: Juggler did not deliver the move to {got['point']} inside the picker: it took {took} s")
            elif verdict == "reached the page":
                failures.append(f"{where}: the move to {got['point']} inside the picker reached the page")
            if any(e in got["page"] for e in ("mousedown", "mouseup", "click")):
                failures.append(f"{where}: the page got clicks at {got['point']}, so no popup covered it: {got['page']}")
            elif not all(isinstance(s, float) and s < IMMEDIATE_S for s in got["took"]):
                failures.append(f"{where}: clicks inside the picker took {got['took']}, want each under {IMMEDIATE_S} s")
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
