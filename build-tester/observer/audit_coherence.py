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
# What each requested OS must claim. PLATFORM_FOR mirrors the table in
# goapi/pkg/fingerprint/coherence_test.go; UA_TOKEN_FOR has no counterpart there and is
# local to this audit.
PLATFORM_FOR = {"windows": "Win32", "macos": "MacIntel", "linux": "Linux x86_64"}
UA_TOKEN_FOR = {"windows": "Windows", "macos": "Macintosh", "linux": "Linux"}
# No screen=, window=, or fingerprint is passed to any launch below, on purpose. This
# audit must exercise the default path a real scraper takes; pinning any of those makes
# launch_options treat the screen as caller-chosen and skip its own corrections -- the
# audit would then be measuring a path nobody uses.

READ = """() => {
  const dpr = window.devicePixelRatio, near = q => matchMedia(q).matches;
  return {
    dpr, mmCoherent: near(`(min-resolution: ${dpr-0.05}dppx)`) && near(`(max-resolution: ${dpr+0.05}dppx)`),
    sw: screen.width, sh: screen.height, aw: screen.availWidth, ah: screen.availHeight,
    ow: outerWidth, oh: outerHeight, iw: innerWidth, ih: innerHeight,
    plat: navigator.platform, ua: navigator.userAgent, touch: navigator.maxTouchPoints,
  };
}"""

def coherence_fails(d, os_name, expected_dpr):
    f = []
    if not (d["iw"] <= d["ow"] <= d["aw"] <= d["sw"]):
        f.append(f"width nest: inner={d['iw']} outer={d['ow']} avail={d['aw']} screen={d['sw']}")
    if not (d["ih"] <= d["oh"] <= d["ah"] <= d["sh"]):
        f.append(f"height nest: inner={d['ih']} outer={d['oh']} avail={d['ah']} screen={d['sh']}")
    if abs(d["dpr"] - expected_dpr) > 0.05:
        f.append(f"dpr {d['dpr']} != expected {expected_dpr}")
    if not d["mmCoherent"]:
        f.append(f"dpr getter {d['dpr']} disagrees with matchMedia (split-brain)")
    # Assert against the OS we ASKED Camoufox for, not against a label re-derived from
    # the readings. Comparing two derived labels passes whenever UA and platform are
    # CONSISTENTLY wrong for the requested OS -- exactly the failure this audit exists
    # to catch -- and both also compare equal when both fall back to "unknown".
    if d["plat"] != PLATFORM_FOR[os_name]:
        f.append(f"platform {d['plat']} != {PLATFORM_FOR[os_name]} requested for {os_name}")
    if UA_TOKEN_FOR[os_name] not in d["ua"]:
        f.append(f"UA lacks {UA_TOKEN_FOR[os_name]!r} requested for {os_name}: {d['ua']}")
    if os_name in ("macos", "linux") and d["touch"] != 0:
        f.append(f"maxTouchPoints={d['touch']} on desktop {os_name}")
    return f

def launch(os_name):
    with Camoufox(headless=True, executable_path=BIN, os=os_name, ff_version=152,
                  i_know_what_im_doing=True) as b:
        p = b.new_context().new_page(); p.goto("about:blank"); return p.evaluate(READ)

def main():
    results = []
    for os_name in OSES:
        for i in range(SAMPLES):
            d = launch(os_name)
            # expected_dpr=1.0 is a SMOKE TEST, not evidence. It hardcodes "headless
            # Firefox floors dpr to 1" -- a second copy of the fact pythonlib encodes
            # for itself, and the reason its dpr-1 screen resample exists. So it passes
            # whether or not that resample ran: this audit cannot detect a regression
            # there, and pythonlib's own tests are what cover it. It also means that if
            # dpr ever stops being 1 in headless (the overrideDPPX work sketched in
            # probe_split.py), this line fails for correct code -- fix the line, not the
            # browser. The audit's real subject is the browser-side coherence below.
            fails = coherence_fails(d, os_name, expected_dpr=1.0)
            results.append({"os": os_name, "i": i, "fails": fails, **d})
            print(f"[{'PASS' if not fails else 'FAIL'}] {os_name}#{i}: "
                  f"screen={d['sw']}x{d['sh']} outer={d['ow']}x{d['oh']} inner={d['iw']}x{d['ih']} dpr={d['dpr']}")
            for x in fails: print("     -", x)
    (HERE / "audit_coherence.json").write_text(json.dumps(results, indent=2))
    bad_oses = sorted({r["os"] for r in results if r["fails"]})
    print("---")
    print(f"{sum(1 for r in results if not r['fails'])}/{len(results)} coherent")
    # Sampling breadth GATES the run. An arm that draws one screen across every sample is
    # effectively n=1, and every other check here (nesting, dpr, platform, UA) is satisfiable
    # by a single fake screen -- so it would report a green 12/12 that means almost nothing.
    # This is not hypothetical: commits a59a98f and ecf15b8 both shipped a passing 12/12
    # whose macOS arm was entirely 960x540. Advisory output was not enough; it must fail.
    collapsed = []
    for o in OSES:
        n = len({(r["sw"], r["sh"]) for r in results if r["os"] == o})
        print(f"  {o}: {n}/{SAMPLES} distinct screens" + ("  <-- COLLAPSED" if n == 1 else ""))
        if n == 1:
            collapsed.append(o)
    if bad_oses:
        print("AUDIT FAIL:", ", ".join(bad_oses)); sys.exit(1)
    if collapsed:
        # n==1 can happen by chance (~1% per arm), so say so rather than asserting a bug.
        print(f"AUDIT FAIL: sampling collapsed for {', '.join(collapsed)} -- every sample drew "
              "the same screen, so the PASS is not evidence. Re-run once; if it repeats, "
              "fingerprint generation is constrained somewhere upstream.")
        sys.exit(1)
    print("AUDIT PASS")

main()
