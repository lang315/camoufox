"""
Diagnostic for #480 (never merged): where the first move after showPicker() is lost.

The sequence of #471's run 43906858431 (head f8ea85e3), looped over headless launches in 3 workers for
1000 s: a click on #open runs showPicker(), a racing click on #t, a new page, a click on #open, one
Marionette read, then moves to (150, 90) / (170, 90) until one stops reaching the page. Juggler logs a
D480 line per acked event (CAMOU_DIAG_480): the chrome-side target of the event, the popups before and
after _popupAt's flush and after the dispatch, the renderer's ack, and the parent's receipt. Odd launches
also run under MOZ_LOG.

    python browser/tests/playwright/patches/picker-first-move-diag.py
"""

import glob
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, marionette_env, resolve_binary  # noqa: E402

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

MOZ_LOG = "MouseBoundaryEvents:5,PointerBoundaryEvents:5,BrowserFocus:5,timestamp,sync"

STATE = """
const out = [];
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  const d = w.document;
  const popups = [...d.querySelectorAll("panel,menupopup,tooltip")].filter(p => p.state !== "closed").map(p => {
    const r = p.getOuterScreenRect(); return {id: p.id, state: p.state, r: [r.left, r.top, r.width, r.height]};
  });
  out.push({focus: d.hasFocus(), popups});
}
return out;
"""


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


def wait_covered_rec(page, deadline_s=10):
    slow, end, i = [], time.monotonic() + deadline_s, 0
    while time.monotonic() < end:
        x, y = 150 + i % 2 * 20, 90
        i += 1
        t = time.monotonic()
        print(f"MOVE {i} ({x}, {y}) {time.time():.3f}", flush=True)
        page.mouse.move(x, y)
        seen = page.evaluate("""([x, y]) => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(
            () => r(document.getElementById('t').dataset.moved === `${x},${y}`))))""", [x, y])
        took = time.monotonic() - t
        if took > 1:
            slow.append({"i": i, "x": x, "y": y, "took": round(took, 2), "seen": seen})
        if not seen:
            return True, slow
    return False, slow


def probe_once(binary, n, logdir):
    from camoufox.sync_api import Camoufox

    port = free_port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    env = {**marionette_env(), "CAMOU_DIAG_480": "1"}
    if n % 2:
        env.update(MOZ_LOG=MOZ_LOG, MOZ_LOG_FILE=str(Path(logdir) / "moz"))
    rec = {"mozlog": bool(n % 2)}
    with Camoufox(executable_path=str(binary), headless=True, os="linux", i_know_what_im_doing=True,
                  args=marionette_args(), env=env, firefox_user_prefs={"marionette.port": port}) as browser:
        keeper = browser.new_page()
        keeper.goto(url, wait_until="load")
        m = Marionette(port)
        page = browser.new_page()
        page.goto(url, wait_until="load")
        print("PHASE p1-click", flush=True)
        page.locator("#open").click()
        print("PHASE p1-racing", flush=True)
        rec["racing"] = timed_click(page)
        page.close()
        page = browser.new_page()
        page.goto(url, wait_until="load")
        print("PHASE p2-click", flush=True)
        page.locator("#open").click()
        rec["p2_after_click"] = m.js(STATE)
        print("PHASE p2-moves", flush=True)
        rec["covered"], rec["slow_moves"] = wait_covered_rec(page)
        rec["after_cover"] = m.js(STATE)
        rec["log"] = page.locator("#log").text_content().split()
        m.close()
    srv.shutdown()
    return rec


def worker(binary, budget_s):
    os.environ["DEBUG"] = "pw:browser"
    end = time.monotonic() + budget_s
    n = 0
    while time.monotonic() < end:
        n += 1
        print(f"LAUNCH {n}", flush=True)
        t = time.monotonic()
        with tempfile.TemporaryDirectory() as logdir:
            try:
                rec = probe_once(binary, n, logdir)
            except Exception as e:
                rec = {"error": f"{type(e).__name__}: {e}"[:1500], "mozlog": bool(n % 2)}
            rec["n"], rec["wall"] = n, round(time.monotonic() - t, 1)
            dropped = any(s["took"] > 4.5 for s in rec.get("slow_moves", []))
            files = sorted(glob.glob(os.path.join(logdir, "moz*")))
            rec["mozlog_lines"] = {os.path.basename(f): sum(1 for _ in open(f, encoding="utf-8", errors="replace")) for f in files}
            if dropped or n in (1, 3):
                for f in files:
                    lines = open(f, encoding="utf-8", errors="replace").read().splitlines()
                    for line in lines[-400:]:
                        print(f"MOZLOG {n} {os.path.basename(f)} {line}", flush=True)
        print("REC " + json.dumps(rec), flush=True)
    return 0


def main() -> int:
    binary = resolve_binary()
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        with hidden_display():
            return worker(binary, float(sys.argv[2]))
    budget = 1000
    workers = 3
    procs = [subprocess.Popen([sys.executable, __file__, "--worker", str(budget)], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) for _ in range(workers)]
    recs = []
    for w, p in enumerate(procs):
        out, _ = p.communicate()
        cur = None
        for line in out.splitlines():
            if line.startswith("LAUNCH "):
                cur = int(line[7:])
            elif "D480 " in line or "[juggler] WARN" in line or line.startswith(("MOVE ", "PHASE ", "MOZLOG ")):
                print(f"W{w} L{cur} {line.strip()[:1500]}")
            elif line.startswith("REC "):
                r = json.loads(line[4:])
                r["worker"] = w
                recs.append(r)
                print(f"W{w} " + line)
    dropped = [r for r in recs if any(s["took"] > 4.5 for s in r.get("slow_moves", []))]
    print(f"DIAG workers={workers} launches={len(recs)} errors={sum(1 for r in recs if r.get('error'))} "
          f"dropped={len(dropped)} dropped-mozlog={sum(1 for r in dropped if r['mozlog'])} "
          f"mozlog-launches={sum(1 for r in recs if r.get('mozlog'))} "
          f"per-worker={[sum(1 for r in recs if r['worker'] == w) for w in range(workers)]}")
    for r in dropped:
        print("DROPPED " + json.dumps({k: r.get(k) for k in ("worker", "n", "wall", "mozlog", "slow_moves", "log")}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
