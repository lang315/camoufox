"""
Diagnostic for #480 (never merged): the first move after showPicker(), old against new MouseDispatch.

#471's sequence (click #open so showPicker() runs, a racing click, a new page, a click on #open, one
Marionette read, then moves to (150, 90) / (170, 90) until one stops reaching the page), looped over
headless launches in 3 workers. Odd launches run main's _popupAt (CAMOU_DIAG_480_OLD), even ones the
routing read. Each launch also moves to a point the picker does not cover (before the covered moves in
half the launches, after in the other half) and into a cross-site iframe; both must reach their page.

    python browser/tests/playwright/patches/picker-first-move-diag.py
"""

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
<iframe id="f" src="FRAME" style="position:absolute;left:320px;top:360px;width:200px;height:120px;border:0"></iframe>
<pre id="log" style="position:absolute;left:600px;top:500px"></pre>
<script>
const log = (m) => document.getElementById('log').append(m + ' ');
const t = document.getElementById('t');
for (const k of ['mousedown', 'mouseup', 'click']) t.addEventListener(k, () => log(k));
document.addEventListener('mousemove', (e) => { document.documentElement.dataset.moved = e.clientX + ',' + e.clientY; }, true);
addEventListener('message', (e) => { document.documentElement.dataset.frameMoved = e.data; });
document.getElementById('open').addEventListener('click', () => {
  const d = document.createElement('input');
  d.type = 'date';
  document.body.prepend(d);
  try { d.showPicker(); log('picker'); } catch (e) { log('picker ' + e.name); }
});
</script></body></html>"""

FRAME = """<!doctype html><html><body style="margin:0;background:#eef">
<script>document.addEventListener('mousemove', (e) => parent.postMessage(e.clientX + ',' + e.clientY, '*'));</script>
</body></html>"""

# Inside every drawn viewport (958 px wide and up), right of the picker (274 px wide from the page's left).
UNCOVERED = (560, 200)
IN_FRAME = (420, 420)  # iframe-local (100, 60)

PIDS = """
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  if (!w.document.hasFocus()) continue;
  const bc = w.gBrowser.selectedBrowser.browsingContext;
  return {top: bc.currentWindowGlobal?.osPid, frames: bc.children.map(c => c.currentWindowGlobal?.osPid)};
}
return null;
"""


def server(body):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(body().encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def timed_click(page):
    t = time.monotonic()
    try:
        page.locator("#t").click(timeout=4000)
        return round(time.monotonic() - t, 2)
    except Exception as e:
        return type(e).__name__


def move(page, x, y, attr="moved", poll_s=0.0):
    """How long a move took and whether the page saw it at (x, y) under `attr` (frame-local for a frame)."""
    t = time.monotonic()
    page.mouse.move(x, y)
    took = round(time.monotonic() - t, 2)
    want = f"{x - 320},{y - 360}" if attr == "frameMoved" else f"{x},{y}"
    end = time.monotonic() + poll_s
    while True:
        seen = page.evaluate("""([a, w]) => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(
            () => r(document.documentElement.dataset[a] === w))))""", [attr, want])
        if seen or time.monotonic() >= end:
            return {"took": took, "seen": seen}
        time.sleep(0.05)


def wait_covered_rec(page, deadline_s=10):
    moves, end, i = [], time.monotonic() + deadline_s, 0
    while time.monotonic() < end:
        x, y = 150 + i % 2 * 20, 90
        i += 1
        print(f"MOVE {i} ({x}, {y}) {time.time():.3f}", flush=True)
        r = move(page, x, y)
        moves.append({"i": i, **r})
        if not r["seen"]:
            return True, moves
    return False, moves


def probe_once(binary, n):
    from camoufox.sync_api import Camoufox

    old = bool(n % 2)
    uncovered_first = bool((n // 2) % 2)
    port = free_port()
    frame_srv = server(lambda: FRAME)
    srv = server(lambda: PAGE.replace("FRAME", f"http://localhost:{frame_srv.server_port}/"))
    url = f"http://127.0.0.1:{srv.server_port}/"
    env = {**marionette_env(), "CAMOU_DIAG_480": "1", **({"CAMOU_DIAG_480_OLD": "1"} if old else {})}
    rec = {"arm": "old" if old else "new", "uncovered_first": uncovered_first}
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
        rec["pids"] = m.js(PIDS)
        rec["viewport"] = page.evaluate("[innerWidth, innerHeight]")
        rec["frames"] = [f.url for f in page.frames]
        print("PHASE p2-moves", flush=True)
        if uncovered_first:
            rec["uncovered"] = move(page, *UNCOVERED)
        rec["covered"], rec["moves"] = wait_covered_rec(page)
        if not uncovered_first:
            rec["uncovered"] = move(page, *UNCOVERED)
        print("PHASE p2-frame", flush=True)
        rec["frame"] = move(page, *IN_FRAME, attr="frameMoved", poll_s=1.0)
        rec["log"] = page.locator("#log").text_content().split()
        m.close()
    srv.shutdown()
    frame_srv.shutdown()
    return rec


def worker(binary, budget_s):
    os.environ["DEBUG"] = "pw:browser"
    end = time.monotonic() + budget_s
    n = 0
    while time.monotonic() < end:
        n += 1
        print(f"LAUNCH {n}", flush=True)
        t = time.monotonic()
        try:
            rec = probe_once(binary, n)
        except Exception as e:
            rec = {"arm": "old" if n % 2 else "new", "error": f"{type(e).__name__}: {e}"[:1500]}
        rec["n"], rec["wall"] = n, round(time.monotonic() - t, 1)
        print("REC " + json.dumps(rec), flush=True)
    return 0


def main() -> int:
    binary = resolve_binary()
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        with hidden_display():
            return worker(binary, float(sys.argv[2]))
    budget = float(os.environ.get("DIAG_480_BUDGET", "2700"))
    workers = 3
    # Each worker writes to its own file: a pipe read only after the worker before it
    # had finished blocked the later workers on a full pipe.
    with tempfile.TemporaryDirectory() as tmp:
        outs = [Path(tmp) / f"w{w}.log" for w in range(workers)]
        procs = []
        for out in outs:
            with open(out, "w", encoding="utf-8") as f:
                procs.append(subprocess.Popen([sys.executable, __file__, "--worker", str(budget)], stdout=f,
                                              stderr=subprocess.STDOUT, text=True))
        for p in procs:
            p.wait()
        texts = [out.read_text(encoding="utf-8", errors="replace") for out in outs]
    recs = []
    for w, out in enumerate(texts):
        cur = None
        for line in out.splitlines():
            if line.startswith("LAUNCH "):
                cur = int(line[7:])
            elif "D480 " in line or "[juggler] WARN" in line or line.startswith(("MOVE ", "PHASE ")):
                print(f"W{w} L{cur} {line.strip()[:1500]}")
            elif line.startswith("REC "):
                r = json.loads(line[4:])
                r["worker"] = w
                recs.append(r)
                print(f"W{w} " + line)
    for arm in ("old", "new"):
        rs = [r for r in recs if r["arm"] == arm]
        ok = [r for r in rs if not r.get("error")]
        first = [r["moves"][0] for r in ok if r.get("moves")]
        print(f"ARM {arm} launches={len(rs)} errors={len(rs) - len(ok)} "
              f"first-covered-dropped={sum(1 for f in first if f['took'] > 4.5)} "
              f"first-covered-reached-page={sum(1 for f in first if f['seen'])} "
              f"uncovered-acked-and-seen={sum(1 for r in ok if r['uncovered']['seen'] and r['uncovered']['took'] < 2)}/{len(ok)} "
              f"frame-acked-and-seen={sum(1 for r in ok if r['frame']['seen'] and r['frame']['took'] < 2)}/{len(ok)} "
              f"frame-oop={sum(1 for r in ok if r['pids'] and r['pids']['frames'] and r['pids']['frames'][0] != r['pids']['top'])}/{len(ok)} "
              f"picker={sum(1 for r in ok if r['log'][:1] == ['picker'])}/{len(ok)}")
    print(f"PER-WORKER {[sum(1 for r in recs if r['worker'] == w) for w in range(workers)]}")
    for r in recs:
        if r.get("error") or (r.get("moves") and r["moves"][0]["took"] > 4.5) or not r.get("uncovered", {}).get("seen") \
                or not r.get("frame", {}).get("seen"):
            print("ODD " + json.dumps(r))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
