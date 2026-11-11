"""
page.mouse.move() reaches the page as a real mouse's motion does in stock Firefox.

A real mouse reports faster than the refresh driver ticks. Stock Firefox
158.0.1 on Linux (GTK, X11) queues the moves in the content process and, at
each tick, dispatches one pointermove/mousemove that carries the queued ones
in getCoalescedEvents(), and a pointerrawupdate for each move as it arrives.
A 125 Hz XTest sweep on Xvfb (three runs, identical):
one pointermove per frame, 2 to 4 coalesced in each, a pointerrawupdate per
report.

Juggler's moves skipped the queue: one pointermove per move, a coalesced list
of length 1, as many pointermoves as pointerrawupdates. No mouse does that.

The guard moves along a 64-point path the way a script does
(page.mouse.move(x, y, steps=63)) and checks the page's counts. It also checks
that the page has the destination as soon as move() returns.

Coalescing needs moves that outrun a refresh tick, so the guard reads the tick from
requestAnimationFrame and the pace from the arrival times of the raw moves, and fails with
SETUP-INVALID when the sweep is not faster. Juggler paces its moves at 8 ms (PageHandler.js
kMoveIntervalMs). On Linux they arrive 8.0 ms apart against a 17.1 ms tick (Tests run 42914357955). On a hosted
Windows runner they arrive 16.0 ms apart (median, max 32.0; performance.now() resolves 1 ms) against a 15.6 ms tick
(run 42909452571) and on a hosted macOS runner 17.0 ms apart against a 16.7 ms tick (run 42923629488); stock's real
input at 25 ms a move gives one pointermove each on Windows. No sweep there can show coalescing, so the runner does
not run the guard on Windows or macOS (NOT_ON).

    python browser/tests/playwright/patches/driven-move-coalescing.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

# Served from 127.0.0.1: pointerrawupdate exists only in a secure context. The
# page records its own events and keeps them in an attribute for the driver.
PAGE = b"""<!doctype html><html><body style="margin:0;width:1200px;height:800px"><script>
  const moves = [], raws = [];
  const keep = () => document.body.dataset.seen = JSON.stringify([moves, raws]);
  addEventListener('pointermove', (e) => { moves.push([e.getCoalescedEvents().length, e.clientX, e.clientY]); keep(); }, true);
  addEventListener('pointerrawupdate', () => { raws.push(performance.now()); keep(); }, true);
  addEventListener('keydown', () => { moves.length = 0; raws.length = 0; keep(); }, true);
</script></body></html>"""
SEEN = "() => JSON.parse(document.body.dataset.seen || '[[], []]')"
# One refresh tick: the median distance between requestAnimationFrame callbacks.
TICK = """() => new Promise((resolve) => {
  const gaps = []; let last;
  const frame = (now) => {
    if (last !== undefined) gaps.push(now - last);
    last = now;
    if (gaps.length < 20) requestAnimationFrame(frame);
    else resolve(gaps.sort((a, b) => a - b)[10]);
  };
  requestAnimationFrame(frame);
})"""
STEPS = 63


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


def probe(binary):
    from camoufox.sync_api import Camoufox

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Camoufox(executable_path=str(binary), headless=False, os="linux", window=(1280, 900)) as browser:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
            tick = page.evaluate(TICK)
            page.mouse.move(100, 100)
            page.wait_for_timeout(300)
            page.keyboard.press("Shift")  # the page starts counting afresh
            page.mouse.move(100 + STEPS * 5, 100 + STEPS * 2, steps=STEPS)
            sweep = page.evaluate(SEEN)
            page.mouse.move(700, 500)
            last = page.evaluate(SEEN)[0][-1]
            return sweep, last, tick
    finally:
        server.shutdown()


def main() -> int:
    with hidden_display("1920x1080"):
        (moves, raws), last, tick = probe(resolve_binary())
    lens = [m[0] for m in moves] or [0]
    gaps = sorted(b - a for a, b in zip(raws, raws[1:]))
    gap = gaps[len(gaps) // 2] if gaps else float("inf")
    failures = []
    # The premise of the two rate checks below is a sweep faster than the refresh tick. Without it nothing
    # queues, in stock as in Camoufox (stock real input at 25 ms a move is one pointermove each), so a
    # sweep that does not outrun the tick measures nothing.
    outran = gap < tick
    if not outran:
        failures.append(f"SETUP-INVALID: the sweep did not outrun the refresh tick (gap {gap:.1f} ms, tick {tick:.1f} ms)")
    if len(raws) != STEPS:
        failures.append(f"{len(raws)} pointerrawupdate for {STEPS} moves: stock fires one per move")
    if sum(lens) != STEPS:
        failures.append(f"pointermoves carry {sum(lens)} coalesced moves, {STEPS} were made")
    if outran and len(moves) > STEPS * 0.7:
        failures.append(f"{len(moves)} pointermoves for {STEPS} moves at 125 Hz: stock dispatches one per frame")
    if outran and sorted(lens)[len(lens) // 2] < 2:
        failures.append(f"coalesced lengths {lens}: stock carries 2 to 4 per frame")
    if not moves or moves[-1][1:] != [100 + STEPS * 5, 100 + STEPS * 2]:
        failures.append(f"the page's last move is {moves[-1] if moves else None} when move() returned")
    if last[1:] != [700, 500]:
        failures.append(f"after move(700, 500) returned, the page's last move is {last}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: {STEPS} moves reach the page as {len(moves)} pointermoves, coalesced {min(lens)}-{max(lens)} "
          f"(raw moves {gap:.1f} ms apart, tick {tick:.1f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
