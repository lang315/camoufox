"""
Verify a font family that is only reachable through its legacy name (name ID 1)
resolves on the FIRST measurement of a fresh browser (#247).

DejaVu Sans Condensed, DejaVu Sans Light and DejaVu Serif Condensed are listed by
the Windows `libreoffice` unit, but the platform registers each face under its
typographic family (name ID 16), "DejaVu Sans" / "DejaVu Serif". Firefox finds a
legacy name through "other family names", which it loads lazily: the first lookup
only schedules the load and answers "no such family" (gfxPlatformFontList::
FindAndAddFamiliesLocked, gfx/thebes/gfxPlatformFontList.cpp), so a page that
measured right after launch drew the fallback font, and a page that measured a few
seconds later drew the real one. font-other-names-sync.patch makes that first lookup
read the names when the page is under a launch-level or a per-context font list. (The pref gfx.font_loader.delay=0 also
resolves the names, but it starts the font loader at once and lifts its time limit:
launch took 1.7 s longer, measured.)

A windows identity asks for the three legacy names and for a name that no font has,
in a fresh browser, and measures each once, before anything else could have loaded
the other names. The unknown name is the control: it is the width the fallback draws,
under each of two fallbacks (monospace, sans-serif). A legacy name that matches it
under both did not resolve; matching one generic alone can be a real face. Each
launch is a new browser, so the lazy load is still pending when it measures. Two
paths are measured: a launch whose `fonts` list is the launch-level mask, and a
browser launched with canvas noise whose NewContext(os="windows") installs the list
for its own context.

Measured red on a macOS arm64 build without the patch: the launch-level path missed
all three names in 8 launches of 8, and the per-context path in 3 of 3. Not measured on Linux or Windows: this guard has only been seen to fail on
macOS, so a green there says the names resolve, not that the guard can catch a miss.

    python browser/tests/playwright/patches/legacy-family-names-first-measure.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import check, resolve_binary  # noqa: E402

LEGACY = ["DejaVu Sans Condensed", "DejaVu Sans Light", "DejaVu Serif Condensed"]
LAUNCHES = 2
NEVER = "Zzz Not A Font"
TEXT = "HxmW0 .8Qgy"
MEASURE = """([text, names]) => {
  const c = document.createElement('canvas').getContext('2d');
  c.fontKerning = 'none';
  const out = {};
  for (const fb of ['monospace', 'sans-serif']) {
    out[fb] = {};
    for (const n of names) { c.font = `72px "${n}", ${fb}`; out[fb][n] = +c.measureText(text).width.toFixed(2); }
  }
  return out;
}"""


def first_measure(binary):
    """The launch-level path: the identity's fonts are the launch mask."""
    from camoufox import launch_options
    from playwright.sync_api import sync_playwright

    names = LEGACY + [NEVER]
    opts = launch_options(headless=True, os="windows", fonts=names, executable_path=str(binary),
                          i_know_what_im_doing=True)
    with sync_playwright() as p:
        browser = p.firefox.launch(**opts)
        page = browser.new_page()
        page.goto("about:blank")
        widths = page.evaluate(MEASURE, [TEXT, names])
        browser.close()
    return widths


def context_first_measure(binary):
    """The per-context path: a browser with no `fonts` of its own, one context claiming windows."""
    import camoufox.sync_api as sync_api
    from camoufox import launch_options
    from playwright.sync_api import sync_playwright

    names = LEGACY + [NEVER]
    draw = sync_api.generate_context_fingerprint

    def with_legacy_names(**kwargs):
        fp = draw(**kwargs)
        fp["config"]["fonts"] += [n for n in LEGACY if n not in fp["config"]["fonts"]]
        return fp

    sync_api.generate_context_fingerprint = with_legacy_names
    try:
        opts = launch_options(headless=True, executable_path=str(binary), canvas_noise=True,
                              i_know_what_im_doing=True)
        with sync_playwright() as p:
            browser = p.firefox.launch(**opts)
            page = sync_api.NewContext(browser, os="windows").new_page()
            page.goto("about:blank")
            widths = page.evaluate(MEASURE, [TEXT, names])
            browser.close()
    finally:
        sync_api.generate_context_fingerprint = draw
    return widths


def missed(widths):
    """The legacy names whose width equals the fallback's under both generics."""
    return [n for n in LEGACY if all(w[n] == w[NEVER] for w in widths.values())]


def main() -> int:
    binary = resolve_binary()
    failures: list = []
    for path, measure in (("launch-level", first_measure), ("per-context", context_first_measure)):
        for launch in range(LAUNCHES):
            widths = measure(binary)
            print(f"  {path} launch {launch + 1}: {widths}")
            check(failures, f"{path} launch {launch + 1}: legacy names that drew the fallback", missed(widths), [])
    if failures:
        print(f"FAIL: {failures}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
