from pathlib import Path
import harness

HERE = Path(__file__).parent

EXPECTED = set(harness.SURFACE_NAMES.values())

def main():
    with harness.serve(HERE) as port, harness.Session(camou_config={"canvas:seed": 424242}) as s:
        s.navigate(f"http://127.0.0.1:{port}/probe_all_surfaces.html")
        s.wait_done(30)
        probe_log = s.expando("__probeLog__")
        snap = s.snapshot()
    recorded = {s for row in snap for s in row["surfaces"]}
    print("probe page results:", probe_log)
    print("observer recorded:", sorted(recorded))
    missing = EXPECTED - recorded
    assert not missing, f"surfaces NOT recorded: {sorted(missing)} | probe={probe_log} | snap={snap}"
    print("PASS: all 7 surfaces recorded")

main()
