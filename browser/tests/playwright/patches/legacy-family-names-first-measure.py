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
read the names when the font list is masked. (The pref gfx.font_loader.delay=0 also
resolves the names, but it starts the font loader at once and lifts its time limit:
launch took 1.7 s longer, measured.)

A windows identity asks for the three legacy names and for a name that no font has,
in a fresh browser, and measures each once, before anything else could have loaded
the other names. The unknown name is the control: it is the width the fallback draws,
under each of two fallbacks (monospace, sans-serif). A legacy name that matches it
did not resolve. Each launch is a new browser, so the lazy load is still pending when
it measures.

Measured red on a macOS arm64 build without the patch: 8 launches in 8 missed all
three names. Not measured on Linux or Windows: this guard has only been seen to fail on
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


def missed(widths):
    """The legacy names whose width equals the fallback's under either generic: a name can
    share a width with one generic, never with the font it should resolve to on both."""
    return [n for n in LEGACY if any(w[n] == w[NEVER] for w in widths.values())]


def main() -> int:
    binary = resolve_binary()
    failures: list = []
    for launch in range(LAUNCHES):
        widths = first_measure(binary)
        print(f"  launch {launch + 1}: {widths}")
        check(failures, f"launch {launch + 1}: legacy names that drew the fallback", missed(widths), [])
    if failures:
        print(f"FAIL: {failures}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
