"""
Diagnostic for #480 (never merged): the first move after showPicker(), old against new MouseDispatch.

Diag 2's setup (run 44232057350), the only one that reproduced (13 of 99): one browser at a time, and
#471's sequence unchanged up to and including the covered moves (click #open so showPicker() runs, a
racing click, a new page, a click on #open, one Marionette read, then moves to (150, 90) / (170, 90)
until one stops reaching #t). Odd launches run main's _popupAt (CAMOU_DIAG_480_OLD), even ones the
routing read. After the covered moves, each launch injects a cross-site iframe and moves to a point the
picker does not cover and into the iframe.

Pre-registered counts, per arm: the trigger (a covered send whose pre-dispatch read, taken without a
flush, has the date picker open at 0x0 and the parent dispatching to something not the browser), and
first-move drops (a covered move over 4.5 s).

    python browser/tests/playwright/patches/picker-first-move-diag.py
"""

import http.server
import json
import os
import re
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

FRAME = """<!doctype html><html><body style="margin:0;background:#eef">
<script>document.addEventListener('mousemove', (e) => parent.postMessage(e.clientX + ',' + e.clientY, '*'));</script>
</body></html>"""

# Added after the covered moves, in the page's main world (a <script> element), so nothing before them changes.
EXTRAS = """(src) => new Promise(r => {
  const s = document.createElement('script');
  s.textContent = `
    document.addEventListener('mousemove', (e) => { document.documentElement.dataset.moved = e.clientX + ',' + e.clientY; }, true);
    addEventListener('message', (e) => { document.documentElement.dataset.frameMoved = e.data; });`;
  document.body.append(s);
  const f = document.createElement('iframe');
  f.style.cssText = 'position:absolute;left:320px;top:360px;width:200px;height:120px;border:0';
  f.onload = () => r(true);
  f.src = src;
  document.body.append(f);
})"""

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

PIDS = """
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  if (!w.document.hasFocus()) continue;
  const bc = w.gBrowser.selectedBrowser.browsingContext;
  return {top: bc.currentWindowGlobal?.osPid, frames: bc.children.map(c => c.currentWindowGlobal?.osPid)};
}
return null;
"""

# Inside every drawn viewport (958 px wide and up), right of the picker (274 px wide from the page's left).
UNCOVERED = (560, 200)
IN_FRAME = (420, 420)  # iframe-local (100, 60)


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


def wait_covered_rec(page, deadline_s=10):
    moves, end, i = [], time.monotonic() + deadline_s, 0
    while time.monotonic() < end:
        x, y = 150 + i % 2 * 20, 90
        i += 1
        t = time.monotonic()
        print(f"MOVE {i} ({x}, {y}) {time.time():.3f}", flush=True)
        page.mouse.move(x, y)
        seen = page.evaluate("""([x, y]) => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(
            () => r(document.getElementById('t').dataset.moved === `${x},${y}`))))""", [x, y])
        moves.append({"i": i, "took": round(time.monotonic() - t, 2), "seen": seen})
        if not seen:
            return True, moves
    return False, moves


def move(page, x, y, attr, poll_s):
    """How long a move took and whether the page saw it at (x, y) under `attr` (frame-local for the frame)."""
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


def probe_once(binary, n):
    from camoufox.sync_api import Camoufox

    old = bool(n % 2)
    port = free_port()
    srv, frame_srv = server(lambda: PAGE), server(lambda: FRAME)
    url = f"http://127.0.0.1:{srv.server_port}/"
    env = {**marionette_env(), "CAMOU_DIAG_480": "1", **({"CAMOU_DIAG_480_OLD": "1"} if old else {})}
    rec = {"arm": "old" if old else "new"}
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
        rec["covered"], rec["moves"] = wait_covered_rec(page)
        rec["after_cover"] = m.js(STATE)
        print("PHASE p2-extras", flush=True)
        page.evaluate(EXTRAS, f"http://localhost:{frame_srv.server_port}/")
        rec["pids"] = m.js(PIDS)
        rec["uncovered"] = move(page, *UNCOVERED, attr="moved", poll_s=0.0)
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


SEND = re.compile(r"D480 \d+ send id=(\d+) (\w+) rel=\(([\d.]+),([\d.]+)\) arm=\w+ oldPopupAt=(\S+) "
                  r"target=\[([^\]]*)\] before=\{([^}]*)\}")
ACK = re.compile(r"D480 \d+ (ack|miss) id=(\d+) ")
PICKER = re.compile(r"DateTimePickerPanel:open:\[([^\]]*)\]")


def trigger(send):
    """A covered send the parent gave to something not the browser while the open picker read 0x0, unflushed."""
    m = PICKER.search(send["before"])
    return not send["browser"] and bool(m) and 0 in [float(v) for v in m[1].split(",")[2:]]


def main() -> int:
    binary = resolve_binary()
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        with hidden_display():
            return worker(binary, float(sys.argv[2]))
    budget = float(os.environ.get("DIAG_480_BUDGET", "2700"))
    # One browser at a time, as in diag 2. The worker writes to a file, not a pipe read only at its end.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "w0.log"
        with open(out, "w", encoding="utf-8") as f:
            subprocess.run([sys.executable, __file__, "--worker", str(budget)], stdout=f, stderr=subprocess.STDOUT,
                           text=True, check=False)
        text = out.read_text(encoding="utf-8", errors="replace")
    recs, sends, acks, cur, phase = [], {}, {}, None, None
    for line in text.splitlines():
        if line.startswith("LAUNCH "):
            cur, phase = int(line[7:]), None
        elif line.startswith("PHASE "):
            phase = line[6:].strip()
            print(f"L{cur} {line.strip()}")
        elif "D480 " in line or "[juggler] WARN" in line or line.startswith("MOVE "):
            print(f"L{cur} {line.strip()[:1500]}")
            s, a = SEND.search(line), ACK.search(line)
            if s:
                sends.setdefault(cur, []).append({"phase": phase, "id": s[1], "type": s[2], "old_popup": s[5] != "null",
                                                  "browser": "=browser" in s[6], "before": s[7]})
            if a:
                acks.setdefault(cur, {})[a[2]] = a[1]
        elif line.startswith("REC "):
            recs.append(json.loads(line[4:]))
            print(line)
    for arm in ("old", "new"):
        rs = [r for r in recs if r["arm"] == arm]
        ok = [r for r in rs if not r.get("error")]
        trig = trig_launches = drops = any_drops = frame_acked = 0
        for r in ok:
            covered = [s for s in sends.get(r["n"], []) if s["phase"] == "p2-moves"]
            hits = sum(1 for s in covered if trigger(s))
            trig, trig_launches = trig + hits, trig_launches + bool(hits)
            drops += 1 if r.get("moves") and r["moves"][0]["took"] > 4.5 else 0
            any_drops += 1 if any(mv["took"] > 4.5 for mv in r.get("moves", [])) else 0
            fr = [s for s in sends.get(r["n"], []) if s["phase"] == "p2-frame" and s["type"] == "mousemove"]
            frame_acked += 1 if fr and fr[0]["browser"] and acks.get(r["n"], {}).get(fr[0]["id"]) == "ack" else 0
        print(f"ARM {arm} launches={len(rs)} errors={len(rs) - len(ok)} trigger-sends={trig} "
              f"trigger-launches={trig_launches} first-covered-dropped={drops} any-covered-dropped={any_drops} "
              f"first-covered-reached-page={sum(1 for r in ok if r.get('moves') and r['moves'][0]['seen'])} "
              f"uncovered-acked-and-seen={sum(1 for r in ok if r['uncovered']['seen'] and r['uncovered']['took'] < 2)}/{len(ok)} "
              f"frame-acked={frame_acked}/{len(ok)} "
              f"frame-seen={sum(1 for r in ok if r['frame']['seen'])}/{len(ok)} "
              f"frame-oop={sum(1 for r in ok if r['pids'] and r['pids']['frames'] and r['pids']['frames'][0] != r['pids']['top'])}/{len(ok)} "
              f"picker={sum(1 for r in ok if r['log'][:1] == ['picker'])}/{len(ok)}")
    for r in recs:
        if r.get("error") or (r.get("moves") and r["moves"][0]["took"] > 4.5) or not r.get("uncovered", {}).get("seen") \
                or not r.get("frame", {}).get("seen"):
            print("ODD " + json.dumps(r))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
