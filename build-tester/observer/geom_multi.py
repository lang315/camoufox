"""Real-pythonlib geometry + dpr measurement (the decisive one that re-grounded
the spec). Multi-sample per OS, HEADLESS = real scraping mode, via Camoufox().
Proves: dpr is coherent through the real launch (=1 headless), and window geometry
is impossible for Windows/macOS (outer>screen / tiny macOS screens) while Linux is
clean. Requires: editable pythonlib (`uv pip install -e ../pythonlib -p .venv`) and
settings/properties.json copied next to the binary (validate_config reads it)."""
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
