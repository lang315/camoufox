"""Diag for #469: the fixed guard's failure lines over many launches, per arm."""

import importlib.util
import json
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

HERE = Path(__file__).resolve().parent
BUDGET = 1500
KINDS = ("a click while the picker opened", "the picker did not open over the page", "Juggler did not deliver",
         "inside the picker reached the page", "the page got clicks", "clicks inside the picker took")


def fixed():
    loader = SourceFileLoader("fixed", str(HERE / "popup-covered-fixed.pyx"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("fixed", loader))
    loader.exec_module(module)
    return module


def worker(arm, budget):
    g, binary = fixed(), resolve_binary()
    proc, display = g.xvfb() if arm == "display" else (None, None)
    end, n = time.monotonic() + budget, 0
    try:
        while time.monotonic() < end:
            n += 1
            try:
                got = g.probe(binary, display)
                lines = g.check(arm, got)
                rec = {"lines": lines, "last_read": got["opened"] if lines else None}
            except Exception as e:
                rec = {"lines": [f"error {type(e).__name__}: {e}"[:200]]}
            rec.update(arm=arm, n=n)
            print("REC " + json.dumps(rec), flush=True)
    finally:
        if proc:
            proc.kill()
            proc.wait()
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], float(sys.argv[3]))
    procs = {arm: subprocess.Popen([sys.executable, __file__, "--worker", arm, str(BUDGET)], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True) for arm in ("headless", "display")}
    for arm, p in procs.items():
        out, _ = p.communicate()
        recs = [json.loads(line[4:]) for line in out.splitlines() if line.startswith("REC ")]
        counts = {}
        for r in recs:
            for line in r["lines"]:
                kind = next((k for k in KINDS if k in line), line[:60])
                counts[kind] = counts.get(kind, 0) + 1
        print(f"DIAG arm={arm} launches={len(recs)} launches-with-a-failure-line={sum(1 for r in recs if r['lines'])} "
              f"by-line={json.dumps(counts)}")
        for r in recs:
            if r["lines"]:
                print("BAD " + json.dumps(r))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
