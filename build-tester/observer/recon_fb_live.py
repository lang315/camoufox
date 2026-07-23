"""Live recon: drive the armed observer against real facebook.com (logged out,
one navigation, no automated loops) to see which of the 7 instrumented surfaces
Meta's real homepage fingerprinting touches -- the operator spot-check REPORT.md
deferred. Separate output (recon_fb_live.json); does not touch the surrogate's
committed recon_fb.json."""
import collections, json, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

URL = "https://www.facebook.com/"
SETTLE = 8  # real page has no __done__ expando; let fingerprinting JS run

def main():
    with harness.Session() as s:          # armed observer, no spoof config (recon is value-agnostic)
        s.navigate(URL)
        time.sleep(SETTLE)
        snap = s.snapshot()
        cookies = s.cookies()
    assert snap, f"no observer rows from {URL} -- blocked, or no surface read before settle"
    all_reqs = [r for row in snap for r in row["requests"]]
    hosts = collections.Counter(r["host"] for r in all_reqs)
    surfaces = collections.Counter()
    for row in snap:
        surfaces.update(row["surfaces"])
    out = {
        "url": URL,
        "surfaces_touched": dict(sorted(surfaces.items())),
        "request_host_counts": dict(hosts.most_common()),
        "cookie_names": sorted({c["name"] for c in cookies}),
        "cookie_hosts": sorted({c["host"] for c in cookies}),
    }
    blob = json.dumps(out, indent=2)
    (HERE / "recon_fb_live.json").write_text(blob)
    print(blob)

main()
