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
parent routes it to; either way it must not wait out the ack deadline. Before
the covered clicks, the guard moves the mouse over #t until a move stops
reaching the page, so it never clicks before the picker covers #t.

Runs headless and, where Xvfb is installed, on a private Xvfb display.

    python browser/tests/playwright/patches/popup-covered-click.py
"""

import http.server
import json
import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, marionette_env, resolve_binary  # noqa: E402

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
const t = document.getElementById('t');
for (const k of ['mousedown', 'mouseup', 'click']) t.addEventListener(k, () => log(k));
t.addEventListener('mousemove', (e) => { t.dataset.moved = e.clientX + ',' + e.clientY; });
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


def wait_covered(page, deadline_s=10):
    """Whether the picker came to cover #t: a move there stops reaching the
    page. Juggler acks a move the parent gives the page, and the page handles
    it at its next refresh tick, before that tick's animation frame callbacks."""
    end = time.monotonic() + deadline_s
    i = 0
    while time.monotonic() < end:
        x, y = 150 + i % 2 * 20, 90
        i += 1
        page.mouse.move(x, y)
        seen = page.evaluate("""([x, y]) => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(
            () => r(document.getElementById('t').dataset.moved === `${x},${y}`))))""", [x, y])
        if not seen:
            return True
    return False



STATE = """
const out = [];
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  const d = w.document, b = w.gBrowser && w.gBrowser.selectedBrowser, bc = b && b.browsingContext;
  const popups = [...d.querySelectorAll("panel,menupopup,tooltip")].filter(p => p.state !== "closed").map(p => {
    const r = p.getOuterScreenRect(); return {id: p.id, state: p.state, r: [r.left, r.top, r.width, r.height]};
  });
  const panel = d.getElementById("DateTimePickerPanel");
  out.push({url: b && b.currentURI && b.currentURI.spec, focus: d.hasFocus(), activeIsBrowser: d.activeElement === b,
            canOpen: bc && bc.canOpenModalPicker, isActive: bc && bc.isActive, activeWin: Services.focus.activeWindow === w,
            panel: panel ? panel.state : null, popups});
}
return out;
"""


_last = [None]


def probe_once(binary):
    from camoufox.sync_api import Camoufox

    port = free_port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    rec = {}
    _last[0] = 'launch'
    with Camoufox(executable_path=str(binary), headless=False, os="linux", i_know_what_im_doing=True,
                  args=marionette_args(), env=marionette_env(), firefox_user_prefs={"marionette.port": port}) as browser:
        # Marionette stays on the newest window at connect; this one outlives both phases' pages.
        keeper = browser.new_page()
        keeper.goto(url, wait_until="load")
        _last[0] = 'marionette-connect'
        m = Marionette(port)
        _last[0] = 'p1'
        page = browser.new_page()
        page.goto(url, wait_until="load")
        page.locator("#open").click()
        rec["racing"] = timed_click(page)
        _last[0] = "p1-state"
        rec["p1_before_close"] = m.js(STATE)
        page.close()
        rec["p1_after_close"] = m.js(STATE)
        _last[0] = "p2"
        page = browser.new_page()
        page.goto(url, wait_until="load")
        rec["p2_before_click"] = m.js(STATE)
        page.locator("#open").click()
        rec["p2_after_click"] = m.js(STATE)
        t = time.monotonic()
        rec["covered"] = wait_covered(page)
        rec["cover_s"] = round(time.monotonic() - t, 2)
        rec["log"] = page.locator("#log").text_content().split()
        if not rec["covered"]:
            rec["p2_at_failure"] = m.js(STATE)
        m.close()
    srv.shutdown()
    return rec


def worker(binary, budget_s):
    end = time.monotonic() + budget_s
    n = 0
    while time.monotonic() < end:
        n += 1
        try:
            rec = probe_once(binary)
        except Exception as e:
            rec = {"error": f"{type(e).__name__}: {e}"[:200], "stage": getattr(e, "stage", None) or _last[0]}
        rec["n"] = n
        print("REC " + json.dumps(rec), flush=True)
    return 0


def main() -> int:
    binary = resolve_binary()
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        with hidden_display():
            return worker(binary, float(sys.argv[2]))
    budget = 420
    workers = int(os.environ.get("DIAG_WORKERS", "2"))
    procs = [subprocess.Popen([sys.executable, __file__, "--worker", str(budget)], stdout=subprocess.PIPE, text=True)
             for _ in range(workers)]
    recs = []
    for p in procs:
        out, _ = p.communicate()
        recs += [json.loads(line[4:]) for line in out.splitlines() if line.startswith("REC ")]
    bad = [r for r in recs if r.get("error") or not r.get("covered")]
    print(f"DIAG workers={workers} launches={len(recs)} not-covered={sum(1 for r in recs if not r.get('covered') and not r.get('error'))} errors={sum(1 for r in recs if r.get('error'))}")
    for r in bad:
        print("BAD " + json.dumps(r))
    for r in recs:
        if r not in bad:
            print("OK " + json.dumps({k: r[k] for k in ("n", "cover_s", "p1_after_close", "p2_before_click") if k in r}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
