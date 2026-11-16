"""Diag for #469: the fixed guard's verdicts over many headless launches."""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

HERE = Path(__file__).resolve().parent


def fixed():
    spec = importlib.util.spec_from_file_location("fixed", HERE / "popup-covered-fixed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verdict(g):
    o = g["opened"]
    if not o or o["state"] != "open":
        return f"not-open:{o and o['state']}"
    if not g.get("point"):
        return "no-point"
    v, took = g["move"]
    clicks = "page-got-clicks" if any(e in g["page"] for e in ("mousedown", "mouseup", "click")) else "clicks-ok"
    slow = "slow-clicks" if not all(isinstance(s, float) and s < 2 for s in g["took"]) else "fast-clicks"
    return f"{v}|{clicks}|{slow}"


def worker(budget):
    mod, binary, end, n = fixed(), resolve_binary(), time.monotonic() + budget, 0
    while time.monotonic() < end:
        n += 1
        try:
            g = mod.probe(binary, None)
            rec = {"n": n, "v": verdict(g), "racing": g["racing"], "move": g.get("move"), "point": g.get("point"),
                   "opened": g["opened"], "page": g["page"]}
        except Exception as e:
            rec = {"n": n, "v": "error", "error": f"{type(e).__name__}: {e}"[:200]}
        print("REC " + json.dumps(rec), flush=True)
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        with hidden_display():
            return worker(float(sys.argv[2]))
    procs = [subprocess.Popen([sys.executable, __file__, "--worker", "1000"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True) for _ in range(3)]
    recs = []
    for p in procs:
        out, _ = p.communicate()
        recs += [json.loads(line[4:]) for line in out.splitlines() if line.startswith("REC ")]
    counts = {}
    for r in recs:
        counts[r["v"]] = counts.get(r["v"], 0) + 1
    print(f"DIAG launches={len(recs)} verdicts={json.dumps(counts)}")
    for r in recs:
        if r["v"] != "covered|clicks-ok|fast-clicks":
            print("ODD " + json.dumps(r))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
