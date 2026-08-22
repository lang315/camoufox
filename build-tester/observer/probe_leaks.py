import json
from pathlib import Path
import harness

HERE = Path(__file__).parent

# What makes a surface a Plan-B spoof candidate is NOT "does it vary between two configs"
# (an un-spoofed surface returns the SAME real device value regardless of config, so a
# config-comparison would mislabel it "constant" and miss it). It is: the surface returns
# a present, non-empty REAL value AND camoufox has no MaskConfig key to spoof it.
# MaskConfig coverage (settings/properties.json): only battery:* and mediaDevices:* have
# keys (already spoofable -> observe-only in Plan B). deviceMemory / plugins / mimeTypes /
# vendor / userAgentData / connection have NO key -> a present non-empty value there leaks
# the real device value.
HAS_KEY = {"battery", "devices"}   # 'devices' == navigator.mediaDevices.enumerateDevices

def empty(v):
    return v is None or v == "<<absent>>" or v == "" or v == []

def main():
    with harness.serve(HERE) as port, harness.Session(camou_config={"canvas:seed": 1}) as s:
        s.navigate(f"http://127.0.0.1:{port}/probe_leaks.html")
        s.wait_done(30)
        vals = s.expando("__leaks__")   # set by the page's own <script>
    assert vals, "probe produced no values"
    table = {k: {"value": vals[k], "present": vals[k] != "<<absent>>",
                 "empty": empty(vals[k]), "has_maskconfig_key": k in HAS_KEY} for k in vals}
    blob = json.dumps(table, indent=2)
    (HERE / "leak_evidence.json").write_text(blob)
    print(blob)
    candidates = [k for k in table if not table[k]["empty"] and not table[k]["has_maskconfig_key"]]
    print("PLAN-B SPOOF CANDIDATES (present real value, no MaskConfig key):", candidates or "none")
    print("SKIP (absent/empty):", [k for k in table if table[k]["empty"]] or "none")
    print("OBSERVE-ONLY (already has MaskConfig key):",
          sorted(k for k in table if table[k]["has_maskconfig_key"]))

main()
