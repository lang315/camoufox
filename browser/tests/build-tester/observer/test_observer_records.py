from pathlib import Path
import harness
from camoufox.host_rendering import add_canvas_placeholder

HERE = Path(__file__).parent

EXPECTED = set(harness.SURFACE_NAMES.values())


def recorded(page, prefs=None):
    with harness.serve(HERE) as port, harness.Session(camou_config={"canvas:seed": 424242}, prefs=prefs) as s:
        s.navigate(f"http://127.0.0.1:{port}/{page}")
        s.wait_done(30)
        probe_log = s.expando("__probeLog__")
        snap = s.snapshot()
    print(f"{page} probe page results:", probe_log)
    return {s for row in snap for s in row["surfaces"]}, probe_log, snap


def main():
    got, probe_log, snap = recorded("probe_all_surfaces.html")
    print("observer recorded:", sorted(got))
    missing = EXPECTED - got
    assert not missing, f"surfaces NOT recorded: {sorted(missing)} | probe={probe_log} | snap={snap}"
    print("PASS: all 7 surfaces recorded")

    # A launch whose canvas the RFP placeholder covers answers getImageData and
    # readPixels from Firefox's placeholder branch; the read must still be recorded (#199).
    covered = {}
    add_canvas_placeholder(covered)
    got, probe_log, snap = recorded("probe_readback.html", covered)
    print("observer recorded (covered launch):", sorted(got))
    missing = {"canvas", "webgl"} - got
    assert not missing, f"covered launch: reads NOT recorded: {sorted(missing)} | probe={probe_log} | snap={snap}"
    print("PASS: getImageData and readPixels recorded on a covered launch")

    # nsScreen caches the spoofed rect per context; the hook sits before the cache, so every
    # read must still reach it. Six reads, each in its own drain window, count six times.
    got, probe_log, snap = recorded("probe_screen_reads.html")
    screen_count = sum(row["surfaces"].get("screen", 0) for row in snap)
    print("screen reads counted:", screen_count, "of", probe_log["reads"])
    assert screen_count >= probe_log["reads"], f"cached screen reads were not recorded: {screen_count} < {probe_log['reads']} | snap={snap}"
    print("PASS: every screen read is recorded, not only the first")

main()
