"""Diag for #469: the sequence of picker reads from showPicker() until its rect stops changing, per arm."""

import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

HERE = Path(__file__).resolve().parent
BUDGET = 1500


def main_guard():
    loader = SourceFileLoader("main_guard", str(HERE / "popup-covered-main.pyx"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("main_guard", loader))
    loader.exec_module(module)
    return module


def seq_probe(g, binary, display):
    import http.server
    import threading

    from camoufox.sync_api import Camoufox
    from helpers import Marionette, free_port, marionette_args, marionette_env

    port = free_port()
    kw = dict(executable_path=str(binary), headless=display is None, os="linux", i_know_what_im_doing=True,
              args=marionette_args(), firefox_user_prefs={"marionette.port": port},
              env={**marionette_env(), **({"DISPLAY": display} if display else {})})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), g.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    with Camoufox(**kw) as browser:
        page = browser.new_page()
        page.goto(url, wait_until="load")
        page.locator("#open").click()
        g.timed_click(page)
        page.close()
        page = browser.new_page()
        page.goto(url, wait_until="load")
        m = Marionette(port)
        try:
            page.locator("#open").click()
            t0 = time.monotonic()
            seq, last, reads = [], "unset", 0
            while time.monotonic() - t0 < 10:
                seen = m.js(g.PANEL)
                t = round((time.monotonic() - t0) * 1000)
                key = None if not seen else (seen["state"], seen["panel"], seen["content"])
                reads += 1
                if key != last:
                    seq.append([t, key, 1])
                    last = key
                else:
                    seq[-1][2] += 1
                if seq and t - seq[-1][0] >= 1000:
                    break
        finally:
            m.close()
    srv.shutdown()
    return {"seq": seq, "reads": reads, "ms": t}


def worker(arm, budget):
    g, binary = main_guard(), resolve_binary()
    proc, display = (None, None)
    if arm == "display":
        proc, display = g.xvfb()
    end, n = time.monotonic() + budget, 0
    try:
        while time.monotonic() < end:
            n += 1
            try:
                rec = seq_probe(g, binary, display)
            except Exception as e:
                rec = {"error": f"{type(e).__name__}: {e}"[:200]}
            rec.update(arm=arm, n=n, display=display)
            print("REC " + json.dumps(rec), flush=True)
    finally:
        if proc:
            proc.kill()
            proc.wait()
    return 0


def analyse(g, rec):
    """What the guard's check and the proposed one would have accepted, against where the rect ended."""
    seq = [(t, k, c) for t, k, c in rec["seq"]]
    final = seq[-1][1]
    ready = lambda k: bool(k and k[0] == "open" and k[1][2] and k[1][3])
    covers = lambda k: bool(k and g.covered_point(k[1], k[2]) is not None)
    cur = next((k for t, k, c in seq if ready(k)), None)
    cur_t = next((t for t, k, c in seq if ready(k)), None)
    new = next(((t, k) for t, k, c in seq if ready(k) and covers(k) and c >= 2), None)
    return {"current_wrong": bool(cur and cur[1] != final[1]), "current_first": cur and cur[1], "current_t": cur_t,
            "lead_wrong": bool(new and new[1][1] != final[1]), "lead_t": new and new[0],
            "lead_none": new is None, "final": final, "final_t": seq[-1][0], "nstates": len(seq)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], float(sys.argv[3]))
    g = main_guard()
    procs = {arm: subprocess.Popen([sys.executable, __file__, "--worker", arm, str(BUDGET)], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True) for arm in ("headless", "display")}
    for arm, p in procs.items():
        out, _ = p.communicate()
        recs = [json.loads(line[4:]) for line in out.splitlines() if line.startswith("REC ")]
        ok = [r for r in recs if "seq" in r]
        an = [analyse(g, r) for r in ok]
        print(f"DIAG arm={arm} launches={len(recs)} errors={len(recs) - len(ok)} "
              f"current-check-accepts-a-non-final-rect={sum(a['current_wrong'] for a in an)} "
              f"lead-check-accepts-a-non-final-rect={sum(a['lead_wrong'] for a in an)} "
              f"lead-check-never-accepts={sum(a['lead_none'] for a in an)}")
        firsts = {}
        for a in an:
            k = json.dumps(a["current_first"])
            firsts[k] = firsts.get(k, 0) + 1
        print(f"FIRST-READY-RECT arm={arm} " + json.dumps(firsts))
        for name in ("current_t", "lead_t", "final_t"):
            xs = sorted(a[name] for a in an if a[name] is not None)
            if xs:
                print(f"MS arm={arm} {name} min={xs[0]} median={statistics.median(xs)} p95={xs[int(len(xs) * .95)]} max={xs[-1]}")
        print(f"NSTATES arm={arm} " + json.dumps(sorted({a['nstates'] for a in an})))
        for r, a in zip(ok, an):
            if a["current_wrong"] or a["lead_wrong"] or a["lead_none"] or a["nstates"] > 3:
                print("ODD " + json.dumps({"arm": arm, "n": r["n"], "seq": r["seq"], "reads": r["reads"], "ms": r["ms"]}))
        for r in recs:
            if "error" in r:
                print("ERR " + json.dumps(r))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
