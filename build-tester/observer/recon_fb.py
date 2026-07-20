import json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 424242}) as s:
            s.navigate(f"http://127.0.0.1:{port}/fb_surrogate.html")
            s.wait_done(30)
            snap = s.snapshot()
            cookies = s.cookies()
    finally:
        stop()
    all_reqs = [r for row in snap for r in row["requests"]]
    fb_hosts = sorted({r["host"] for r in all_reqs if "facebook" in r["host"] or "fbcdn" in r["host"] or "fbcdn.net" in r["url"]})
    out = {
        "observer_surfaces": [{"site": r["site"], "surfaces": r["surfaces"]} for r in snap],
        "fb_request_hosts": fb_hosts,
        "fb_request_count": sum(1 for r in all_reqs if "facebook" in r["host"] or "fbcdn" in r["host"]),
        "cookie_names": sorted({c["name"] for c in cookies}),
    }
    (HERE / "recon_fb.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    assert snap, "surrogate produced no observer rows — check network egress to connect.facebook.net"

main()
