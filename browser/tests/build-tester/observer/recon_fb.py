import json
from pathlib import Path
import harness

HERE = Path(__file__).parent

def main():
    with harness.serve(HERE) as port, harness.Session(camou_config={"canvas:seed": 424242}) as s:
        s.navigate(f"http://127.0.0.1:{port}/fb_surrogate.html")
        s.wait_done(30)
        snap = s.snapshot()
        cookies = s.cookies()
    assert snap, "surrogate produced no observer rows — check network egress to connect.facebook.net"
    all_reqs = [r for row in snap for r in row["requests"]]
    def is_fb(r): return "facebook" in r["host"] or "fbcdn" in r["host"] or "fbcdn.net" in r["url"]
    fb_reqs = [r for r in all_reqs if is_fb(r)]
    out = {
        "observer_surfaces": [{"site": r["site"], "surfaces": r["surfaces"]} for r in snap],
        "fb_request_hosts": sorted({r["host"] for r in fb_reqs}),
        "fb_request_count": len(fb_reqs),
        "cookie_names": sorted({c["name"] for c in cookies}),
    }
    blob = json.dumps(out, indent=2)
    (HERE / "recon_fb.json").write_text(blob)
    print(blob)

main()
