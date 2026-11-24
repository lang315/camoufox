"""
mouse.wheel() reaches the page as a mouse wheel does in stock Firefox.

A wheel turns in notches. On Linux (GTK, X11) stock Firefox 158.0.1 delivers
each notch as its own `wheel` event: deltaMode 1 (lines), deltaY 6,
wheelDeltaY -120, then DOMMouseScroll with detail 3 and MozMousePixelScroll
with detail three lines (60 for the 20 px lines of the GTK fonts), and the scroller
moves six lines, 120 px, per notch. Measured with XTest button 5 on Xvfb (three runs,
identical). docs/input-dispatch.md has the Windows measurement, which has the
same shape with that platform's line height: three native lines need no per-OS constant.
The pixels are checked against what one arrow key press scrolls, read from scrollTop at the scroller's
scrollend: three lines because toolkit.scrollbox.verticalScrollDistance is 3, and not a page because three
lines are shorter than the scroller. window.scrollByLines(1) is no read for it: it scrolls after it
returns, in stock 159.0 as in this browser (read at once: 0; a second later: 34 px; diag-53), so it
gives no value to read at a known moment.

macOS differs (driven-wheel-notches-macos.py).

Juggler once sent the requested pixels instead: deltaMode 0, deltaY 100,
wheelDeltaY -300, DOMMouseScroll detail 5. No wheel produces that, and a page
reads it off the first event.

One mouse.wheel(dx, dy) call is one wheel event; the browser adds no pacing or
splitting of its own (a driver that wants a person's strokes sends one call per
notch, on its own schedule). On Linux and Windows 100 px is one notch, rounding,
at least one, and the notches of a call ride in that one event, as a
WM_MOUSEWHEEL of N x 120 (WinMouseScrollHandler) or a GTK smooth delta of N
does: deltaY 6 per notch, wheelDeltaY -120 per notch. On macOS the call is one
event of round(px / 16) lines.

Gecko scrolls at most a page per wheel event (EventStateManager::DoScrollText),
so the scroller is taller than the longest turn here and in driven-wheel-notches-macos.py.

    python browser/tests/playwright/patches/driven-wheel-notches.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:0;font:14px/18px sans-serif">
<div id="s" tabindex="0" style="position:absolute;left:40px;top:40px;width:300px;height:1200px;overflow:auto">
<div style="width:3000px;height:3000px"></div></div></body></html>"""
ARROW = """() => {
  const s = document.getElementById('s');
  window.__arrow = new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 5000);
    s.addEventListener('scrollend', () => { clearTimeout(timer); resolve(s.scrollTop); }, {once: true});
  });
}"""
RECORD = """() => {
  window.__events = [];
  const s = document.getElementById('s');
  const on = (e) => window.__events.push(e.type === 'wheel'
    ? ['wheel', e.deltaMode, e.deltaX, e.deltaY, e.wheelDeltaY, Math.round(e.timeStamp)]
    : [e.type, e.detail]);
  for (const t of ['wheel', 'DOMMouseScroll', 'MozMousePixelScroll']) s.addEventListener(t, on);
}"""

# One notch of stock on GTK/X11 (158.0.1) and on Windows (159.0, docs/input-dispatch.md): three lines. The
# pixels are those of three of the scroller's own lines, which an arrow key scrolls too (diag-52: 60 px on
# Linux, 57 on Windows, 51 under the macOS identity, equal to a notch's MozMousePixelScroll on each),
# so a notch is checked against a scroll the wheel did not make.
def notched(n, step):
    """One event carrying n notches: each field is n times one notch's."""
    return [["wheel", 1, 0, 6 * n, -120 * n], ["DOMMouseScroll", 3 * n], ["MozMousePixelScroll", step * n]]


def probe(binary, os, turns):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os=os, window=(1280, 900)) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        # One arrow key press scrolls toolkit.scrollbox.verticalScrollDistance (3) lines by a path the wheel does
        # not take, and not a page, since three lines are shorter than the scroller. It is read at its
        # scrollend, not after a fixed wait.
        page.evaluate(ARROW)
        page.focus("#s")
        page.keyboard.press("ArrowDown")
        step = page.evaluate("() => window.__arrow")
        out = {"step": step or 0, "arrow": f"scrollTop {page.evaluate('document.getElementById(\'s\').scrollTop')}"}
        page.evaluate("() => { document.getElementById('s').scrollTop = 0; }")
        page.mouse.move(190, 140)
        page.evaluate(RECORD)
        for name, dy in turns:
            page.evaluate("() => { window.__events = []; document.getElementById('s').scrollTop = 0; }")
            page.mouse.wheel(0, dy)
            page.wait_for_timeout(800)
            out[name] = (page.evaluate("window.__events"), page.evaluate("document.getElementById('s').scrollTop"))
        return out


def notch_failures(got):
    failures = []
    step = got["step"]
    if not step:
        failures.append(f"ArrowDown did not finish scrolling ({got['arrow']})")
    elif step * 2 % 3 or not 24 <= step <= 120:
        failures.append(f"an arrow key scrolled the scroller {step} px: three lines of 8 to 40 px, in half pixels, were expected")
    # The line may be fractional (19.5 px on a local Mac, #461). Gecko rounds it to whole pixels
    # for MozMousePixelScroll (EventStateManager: CSSIntSize::FromAppUnitsRounded) and scrolls its exact height.
    line = step / 3
    for name, notches in (("one", 1), ("three", 3), ("short", 1)):
        events, scrolled = got[name]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        expected = notched(notches, 3 * int(line + 0.5))
        if shape != expected:
            failures.append(f"mouse.wheel ({name}) delivered {shape}, expected {expected}")
        if scrolled != 2 * step * notches:
            failures.append(f"mouse.wheel ({name}) scrolled {scrolled} px, stock {2 * step * notches} (six lines of {line} px a notch)")
    return failures


def main() -> int:
    with hidden_display("1920x1080"):
        binary = resolve_binary()
        got = probe(binary, "linux", (("one", 100), ("three", 300), ("short", 30)))
    failures = notch_failures(got)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: one mouse.wheel call is one native wheel event ({got['step'] / 3} px lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
