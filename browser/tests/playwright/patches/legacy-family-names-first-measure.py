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
read the names when a Camoufox font list applies to the page. (The pref
gfx.font_loader.delay=0 also resolves the names, but it starts the font loader at
once and lifts its time limit: launch took 1.7 s longer, measured.)

An identity whose `fonts` are the three legacy names measures each of them in
a fresh browser, then measures them again every 2 s until the loader has run (the
widths stop changing, 10 s at least, 30 s at most). The tell is a name whose first
width differs from its settled width. A name that resolves keeps its width, so
first == settled does not depend on which generic the fallback is. The reference
is the same name in the same page, so both sides are about the same face. A fallback name
(`Zzz Not A Font`) is measured too, but only to show the arm is not vacuous: at
least one legacy name must settle on a width other than the fallback's. It is not
the pass/fail control, because with these `fonts` the generics resolve to one of
the allowed legacy faces themselves (on Linux, monospace draws DejaVu Sans
Condensed, so that name's width equals the fallback's whether or not it resolved).

The identity is a `windows` one, except on a Windows host: there it uses the host's
fonts, which hold no DejaVu, so every width would be the fallback's. A Windows host
gets `linux`, which reaches the Windows-only branch of SharedFontList::FindFamily that
answers a legacy name with its base family's face before the names load (#319).

Measured red on a macOS arm64 build without the patch: the first width was the
fallback's in 8 launches of 8. Measured red on Windows (a linux identity) on
v158.0.1-beta.34-fork.1, run 40666976745: ['DejaVu Sans Condensed']. Not measured
red on Linux, where no build without the patch was available, so a green there says
the names resolve at once, not that this guard can catch a miss on it. The per-context font
list (Juggler setFontList) is not exercised: a context's list is intersected with
the launch-level list, so it cannot be measured apart from the launch-level one.

    python browser/tests/playwright/patches/legacy-family-names-first-measure.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import check, resolve_binary  # noqa: E402

LEGACY = ["DejaVu Sans Condensed", "DejaVu Sans Light", "DejaVu Serif Condensed"]
NEVER = "Zzz Not A Font"
SETTLE_MIN_S, SETTLE_MAX_S, POLL_S = 10, 30, 2
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


def first_and_settled(binary, identity, names):
    """The widths of the first measurement and of the one after they stopped changing."""
    from camoufox import launch_options
    from playwright.sync_api import sync_playwright

    opts = launch_options(headless=True, os=identity, fonts=names, executable_path=str(binary),
                          i_know_what_im_doing=True)
    with sync_playwright() as p:
        browser = p.firefox.launch(**opts)
        page = browser.new_page()
        page.goto("about:blank")
        first = page.evaluate(MEASURE, [TEXT, names])
        settled, stable, started = first, 0, time.monotonic()
        while time.monotonic() - started < SETTLE_MAX_S:
            time.sleep(POLL_S)
            latest = page.evaluate(MEASURE, [TEXT, names])
            stable = stable + 1 if latest == settled else 0
            settled = latest
            if stable >= 2 and time.monotonic() - started >= SETTLE_MIN_S:
                break
        browser.close()
    return first, settled


def late(first, settled):
    """The legacy names whose first width is not the width they settled on."""
    return [n for n in LEGACY if any(first[g][n] != settled[g][n] for g in settled)]


def resolved(settled):
    """The legacy names whose settled width differs from the fallback's under some generic."""
    return [n for n in LEGACY if any(w[n] != w[NEVER] for w in settled.values())]


HOST_LEGACY = ["Segoe UI Semibold", "Segoe UI Light"]


def windows_host_parity(binary, failures):
    """A windows identity on a Windows host reads legacy names as stock Firefox does (#321).

    "Segoe UI Light" shares its base family, "Segoe UI", with "Segoe UI Semibold". Stock
    answers the first of them with the base family's face, and the second, once the base's
    face names have been read, not at all until the font loader has run: that lookup
    reads as the never-font. A masked page that read the names at once would draw Light's
    own face. The never-font is measured in the same call and the same generic pass, so
    both sides are about the same lookup state; Light's own width happens to differ from
    the never-font's, but nothing guarantees it, so the settled side compares Light with
    itself under the other generic, which a resolved name keeps. The loader's delay is 60 s
    on Windows and camoufox.cfg does not set it, but the miss defers to the idle queue and
    the names were read by 15 s on the runner; the first reading is one synchronous call.
    """
    first, settled = first_and_settled(binary, "windows", HOST_LEGACY + [NEVER])
    light = HOST_LEGACY[1]
    print(f"  host first:   {first}")
    print(f"  host settled: {settled}")
    check(failures, "first lookup of the base family's second legacy name reads as the never-font",
          first["monospace"][light], first["monospace"][NEVER])
    check(failures, "first lookup of the base family's first legacy name answers (the arm is not vacuous)",
          first["monospace"][HOST_LEGACY[0]] != first["monospace"][NEVER], True)
    check(failures, "the second legacy name settled on its own face (same width under both generics)",
          settled["monospace"][light], settled["sans-serif"][light])


def main() -> int:
    binary = resolve_binary()
    failures: list = []
    identity = "linux" if sys.platform == "win32" else "windows"
    first, settled = first_and_settled(binary, identity, LEGACY + [NEVER])
    print(f"  first:   {first}")
    print(f"  settled: {settled}")
    check(failures, "legacy names whose first width was not their settled width", late(first, settled), [])
    check(failures, "at least one legacy name settled on a width other than the fallback's",
          bool(resolved(settled)), True)
    if sys.platform == "win32":
        windows_host_parity(binary, failures)
    if failures:
        print(f"FAIL: {failures}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
