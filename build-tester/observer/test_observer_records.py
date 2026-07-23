import sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

EXPECTED = set(harness.SURFACE_NAMES.values())

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 424242}) as s:
            s.navigate(f"http://127.0.0.1:{port}/probe_all_surfaces.html")
            s.wait_done(30)
            # window.wrappedJSObject: see harness.wait_done() -- plain window.__probeLog__
            # reads the Xray view (always undefined for a page-set expando); wrappedJSObject
            # waives the Xray to read the real value.
            probe_log = s.eval_content("return window.wrappedJSObject.__probeLog__;")
            snap = s.snapshot()
    finally:
        stop()
    recorded = {s for row in snap for s in row["surfaces"]}
    print("probe page results:", probe_log)
    print("observer recorded:", sorted(recorded))
    missing = EXPECTED - recorded
    assert not missing, f"surfaces NOT recorded: {sorted(missing)} | probe={probe_log} | snap={snap}"
    print("PASS: all 7 surfaces recorded")

main()
