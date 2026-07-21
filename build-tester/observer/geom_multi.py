"""Real-pythonlib geometry + dpr measurement, multi-sample per OS, HEADLESS =
real scraping mode, via Camoufox(). Result on current pythonlib: dpr AND window
geometry are both coherent for all OSes (12/12).

HISTORY: this script once appeared to show impossible geometry (outer>screen,
tiny macOS screens). That was a STALE-VENV artifact -- cloverlabs-camoufox==0.6.0
physically shadowed the editable .pth redirect and ran pre-#647/#666 code
(importlib.metadata still reported the editable version, masking it). Not a bug.

Setup (order matters -- mirror build-tester/run_tests.sh:60):
  uv pip uninstall cloverlabs-camoufox -p .venv     # FIRST, or you exercise stale code
  uv pip install -e ../pythonlib -p .venv
  cp ../settings/properties.json <binary_dir>/properties.json   # validate_config reads it"""
from camoufox.sync_api import Camoufox

BIN = "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"
JS = ("() => ({sw:screen.width, sh:screen.height, aw:screen.availWidth, ah:screen.availHeight,"
      " ow:outerWidth, oh:outerHeight, iw:innerWidth, ih:innerHeight, dpr:devicePixelRatio})")

def one(os_name):
    with Camoufox(headless=True, executable_path=BIN, os=os_name, ff_version=152, i_know_what_im_doing=True) as b:
        p = b.new_context().new_page(); p.goto("about:blank"); d = p.evaluate(JS)
    nest = d["iw"] <= d["ow"] <= d["aw"] <= d["sw"] and d["ih"] <= d["oh"] <= d["ah"] <= d["sh"]
    print(f"  [{'ok ' if nest else 'BAD'}] dpr={d['dpr']} screen={d['sw']}x{d['sh']} "
          f"avail={d['aw']}x{d['ah']} outer={d['ow']}x{d['oh']} inner={d['iw']}x{d['ih']}")
    return nest, d["sw"]

for os_name in ("windows", "macos", "linux"):
    print(f"== {os_name} ==")
    rows = [one(os_name) for _ in range(4)]
    bad = sum(1 for ok, _ in rows if not ok)
    smalls = [w for ok, w in rows if w < 1280]
    print(f"  -> {bad}/{len(rows)} broken nesting; screens<1280w: {smalls or 'none'}")
