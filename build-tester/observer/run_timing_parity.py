import statistics, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

def measure(arm, port):
    with harness.Session(arm=arm) as s:
        s.navigate(f"http://127.0.0.1:{port}/timing_probe.html")
        s.wait_done(30)
        # page <script> set __timingResult__ on the real window; read it through
        # the Marionette Xray boundary via wrappedJSObject.
        return s.eval_content("return window.wrappedJSObject.__timingResult__;")

def main():
    port, stop = harness.serve(HERE)
    try:
        unarmed = [measure(False, port) for _ in range(3)]
        armed   = [measure(True, port)  for _ in range(3)]
    finally:
        stop()
    def med(runs, op): return statistics.median(x[op]["median"] for x in runs if x and x.get(op))
    ok = True
    measured = 0
    for op in ("toDataURL","getParameter"):
        u, a = med(unarmed, op), med(armed, op)
        if u <= 1e-6:
            if a <= 1e-6:
                print(f"SKIP: {op} unmeasurable in both arms (floored to 0 by privacy.reduceTimerPrecision; not an instrumented path)")
                continue
            # unarmed floored but armed measurable => armed overhead made it measurable: the strongest possible signal
            print(f"FINDING: {op} unmeasurable unarmed but armed={a:.4f}ms — armed overhead made a previously-immeasurable op measurable")
            ok = False; measured += 1
            continue
        ratio = a / u
        measured += 1
        print(f"{op}: unarmed={u:.4f}ms armed={a:.4f}ms ratio={ratio:.3f}")
        if not (ratio < 1.5): ok = False
    assert measured >= 1, "no op was measurable — cannot assess timing parity"
    assert ok, "an instrumented op's armed run is measurably slower than unarmed — ring-buffer hot path too heavy"
    print("PASS: timing parity within band")

main()
