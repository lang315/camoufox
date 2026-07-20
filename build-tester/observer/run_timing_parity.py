import statistics, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

def measure(arm):
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(arm=arm) as s:
            s.navigate(f"http://127.0.0.1:{port}/timing_probe.html")
            s.wait_done(30)
            # page <script> set __timingResult__ on the real window; read it through
            # the Marionette Xray boundary via wrappedJSObject.
            return s.eval_content("return window.wrappedJSObject.__timingResult__;")
    finally:
        stop()

def main():
    unarmed = [measure(False) for _ in range(3)]
    armed   = [measure(True)  for _ in range(3)]
    def med(runs, op): return statistics.median(x[op]["median"] for x in runs if x and x.get(op))
    ok = True
    for op in ("toDataURL","getParameter"):
        u, a = med(unarmed, op), med(armed, op)
        ratio = a / u if u else float("nan")
        print(f"{op}: unarmed={u:.4f}ms armed={a:.4f}ms ratio={ratio:.3f}")
        if not (ratio < 1.5): ok = False
    assert ok, "armed run measurably slower than unarmed band — ring-buffer hot path too heavy"
    print("PASS: timing parity within band")

main()
