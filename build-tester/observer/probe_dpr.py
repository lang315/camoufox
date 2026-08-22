"""Empirical dpr-leak test. MUST run headful: headless Firefox forces
devicePixelRatio=1.0 (no real display), which would mask a host leak. On this
Retina Mac the real host dpr is 2.0, so:
  arm A (no config)      -> baseline real host dpr
  arm B (Windows 1080p)  -> spoofed-or-leaked dpr
  B == A  => dpr leaks the host value (dpr-fix is real scope)
  B != A & coherent with the claimed 1080p desktop => already spoofed (no-op)
Also reads screen + platform to confirm the other spoofs apply."""
import json, os
from marionette_driver.marionette import Marionette
import harness

BIN = harness.default_binary()
WIN = {
    "screen.width": 1920, "screen.height": 1080,
    "screen.availWidth": 1920, "screen.availHeight": 1040,
    "navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "navigator.platform": "Win32",
    "navigator.oscpu": "Windows NT 10.0; Win64; x64",
}
READ = ("return JSON.stringify({dpr:window.devicePixelRatio,"
        "sw:screen.width,sh:screen.height,plat:navigator.platform,"
        "ua:navigator.userAgent});")

def arm(label, config):
    if config is None: os.environ.pop("CAMOU_CONFIG", None)
    else: os.environ["CAMOU_CONFIG"] = json.dumps(config)
    m = Marionette(bin=BIN, port=0, headless=False)  # HEADFUL — dpr needs a real display
    m.start_session()
    try:
        m.navigate("data:text/html,<title>dpr</title>")
        return label, json.loads(m.execute_script(READ))
    finally:
        m.cleanup()

def main():
    results = [arm("A_noconfig", None), arm("B_win1080p", WIN)]
    for label, r in results:
        print(f"{label}: dpr={r['dpr']} screen={r['sw']}x{r['sh']} platform={r['plat']}")
    d = dict(results); a, b = d["A_noconfig"], d["B_win1080p"]
    print("---")
    print(f"host real dpr (arm A) = {a['dpr']}")
    print(f"spoofed-arm dpr (arm B) = {b['dpr']}")
    if b["dpr"] == a["dpr"]:
        print(f"VERDICT: dpr LEAKS host ({b['dpr']}) despite Windows-1080p config -> dpr-fix is REAL scope")
    else:
        print(f"VERDICT: dpr changed with config ({a['dpr']}->{b['dpr']}) -> spoofed/derived, dpr-fix likely no-op")
    print(f"screen spoof applied: {b['sw']}x{b['sh']} (expect 1920x1080), platform={b['plat']} (expect Win32)")

main()
