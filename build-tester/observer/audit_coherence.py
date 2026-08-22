"""Cross-layer coherence audit for FB's read surface, via the REAL pythonlib +
Playwright launch (Marionette is banned here -- it bypasses Juggler and
mismeasures dpr). Asserts geometry nesting, dpr coherence, and navigator
consistency. Headless is the primary (real scraping) mode; headless floors dpr
to 1, so the dpr assertion expects 1 here and a headful spot-check covers >1.
See the module docstring in geom_multi.py for the one-time env setup."""
import json, sys
from pathlib import Path
from camoufox.sync_api import Camoufox
import harness   # stdlib-only at import time; does not pull in Marionette

HERE = Path(__file__).parent
BIN = harness.default_binary()
SAMPLES = 4
OSES = ("windows", "macos", "linux")

READ = """() => {
  const dpr = window.devicePixelRatio, near = q => matchMedia(q).matches;
  return {
    dpr, mmCoherent: near(`(min-resolution: ${dpr-0.05}dppx)`) && near(`(max-resolution: ${dpr+0.05}dppx)`),
    sw: screen.width, sh: screen.height, aw: screen.availWidth, ah: screen.availHeight,
    ow: outerWidth, oh: outerHeight, iw: innerWidth, ih: innerHeight,
    plat: navigator.platform, ua: navigator.userAgent, touch: navigator.maxTouchPoints,
  };
}"""

def coherence_fails(d, expected_dpr):
    f = []
    if not (d["iw"] <= d["ow"] <= d["aw"] <= d["sw"]):
        f.append(f"width nest: inner={d['iw']} outer={d['ow']} avail={d['aw']} screen={d['sw']}")
    if not (d["ih"] <= d["oh"] <= d["ah"] <= d["sh"]):
        f.append(f"height nest: inner={d['ih']} outer={d['oh']} avail={d['ah']} screen={d['sh']}")
    if abs(d["dpr"] - expected_dpr) > 0.05:
        f.append(f"dpr {d['dpr']} != expected {expected_dpr}")
    if not d["mmCoherent"]:
        f.append(f"dpr getter {d['dpr']} disagrees with matchMedia (split-brain)")
    ua_os = "Windows" if "Windows" in d["ua"] else "Mac" if "Macintosh" in d["ua"] else "Linux" if "Linux" in d["ua"] else "?"
    plat_os = "Windows" if d["plat"] == "Win32" else "Mac" if d["plat"] == "MacIntel" else "Linux" if "Linux" in d["plat"] else "?"
    if ua_os != plat_os:
        f.append(f"platform {d['plat']} != UA OS {ua_os}")
    if d["plat"] in ("MacIntel", "Linux x86_64") and d["touch"] != 0:
        f.append(f"maxTouchPoints={d['touch']} on desktop {d['plat']}")
    return f

def launch(os_name):
    with Camoufox(headless=True, executable_path=BIN, os=os_name, ff_version=152, i_know_what_im_doing=True) as b:
        p = b.new_context().new_page(); p.goto("about:blank"); return p.evaluate(READ)

def main():
    results = []
    for os_name in OSES:
        for i in range(SAMPLES):
            d = launch(os_name)
            fails = coherence_fails(d, expected_dpr=1.0)
            results.append({"os": os_name, "i": i, "fails": fails, **d})
            print(f"[{'PASS' if not fails else 'FAIL'}] {os_name}#{i}: "
                  f"screen={d['sw']}x{d['sh']} outer={d['ow']}x{d['oh']} inner={d['iw']}x{d['ih']} dpr={d['dpr']}")
            for x in fails: print("     -", x)
    (HERE / "audit_coherence.json").write_text(json.dumps(results, indent=2))
    bad_oses = sorted({r["os"] for r in results if r["fails"]})
    print("---")
    print(f"{sum(1 for r in results if not r['fails'])}/{len(results)} coherent")
    if bad_oses:
        print("AUDIT FAIL:", ", ".join(bad_oses)); sys.exit(1)
    print("AUDIT PASS")

main()
