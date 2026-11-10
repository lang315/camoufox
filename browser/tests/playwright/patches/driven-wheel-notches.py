"""
mouse.wheel() reaches the page as a mouse wheel does in stock Firefox.

A wheel turns in notches. On Linux (GTK, X11) stock Firefox 158.0.1 delivers
each notch as its own `wheel` event: deltaMode 1 (lines), deltaY 6,
wheelDeltaY -120, then DOMMouseScroll with detail 3 and MozMousePixelScroll
with detail three lines (60 for the 20 px lines of the GTK fonts), and the scroller
moves six lines, 120 px, per notch. Measured with XTest button 5 on Xvfb (three runs,
identical). docs/input-dispatch.md has the Windows measurement, which has the
same shape with that platform's line height: three native lines need no per-OS constant.
The line is read with window.scrollByLines(1) on a page whose root has the scroller's font, so the
pixels are checked against a line that the wheel's own events did not supply.

macOS differs (driven-wheel-notches-macos.py).

Juggler sent the requested pixels instead, unless humanize was on: deltaMode 0,
deltaY 100, wheelDeltaY -300, DOMMouseScroll detail 5, one event however far
the scroll. No wheel produces that, and a page reads it off the first event.

mouse.wheel(dx, dy) turns 100 px into one notch, rounding, at least one; the
notches of one call arrive tens of milliseconds apart. A long wheel leaves the
browser-wide activation slot free between them, so input in another context does
not wait for it to finish.

The scroller is 600 px tall, for the reason given in driven-wheel-notches-macos.py.

    python browser/tests/playwright/patches/driven-wheel-notches.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html style="font:14px/18px sans-serif"><body style="margin:0">
<div id="s" style="position:absolute;left:40px;top:40px;width:300px;height:600px;overflow:auto">
<div style="width:3000px;height:3000px"></div></div></body></html>"""
LINE = """() => {
  document.body.style.height = '5000px';
  window.scrollByLines(1);
  const line = window.scrollY;
  window.scrollTo(0, 0);
  document.body.style.height = '';
  return line;
}"""
RECORD = """() => {
  window.__events = [];
  const s = document.getElementById('s');
  const on = (e) => window.__events.push(e.type === 'wheel'
    ? ['wheel', e.deltaMode, e.deltaX, e.deltaY, e.wheelDeltaY, Math.round(e.timeStamp)]
    : [e.type, e.detail]);
  for (const t of ['wheel', 'DOMMouseScroll', 'MozMousePixelScroll']) s.addEventListener(t, on);
}"""

# One notch of stock on GTK/X11 (158.0.1) and on Windows (159.0, docs/input-dispatch.md): three lines, so the
# pixels are three and six of the scroller's own lines, which the guard reads with scrollByLines below.
def notch(line):
    return [["wheel", 1, 0, 6, -120], ["DOMMouseScroll", 3], ["MozMousePixelScroll", 3 * line]]


def probe(binary, os, turns):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os=os, window=(1280, 900)) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        # The window scrolls by one line through a call the wheel does not take, using the root's font
        # (the same as the scroller's, set on <html>), so the line the wheel's pixels are checked against
        # is not read off the wheel's own events. The page is made tall for the call and put back after.
        out = {"line": page.evaluate(LINE)}
        page.mouse.move(190, 140)
        page.evaluate(RECORD)
        for name, dy in turns:
            page.evaluate("() => { window.__events = []; document.getElementById('s').scrollTop = 0; }")
            page.mouse.wheel(0, dy)
            page.wait_for_timeout(800)
            out[name] = (page.evaluate("window.__events"), page.evaluate("document.getElementById('s').scrollTop"))
        return out


async def contended_wheel(binary):
    """Click in one context while another scrolls. The stamps are the wheel's."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=False, os="linux", window=(1280, 900)) as browser:
        pages = []
        for _ in range(2):
            page = await (await browser.new_context()).new_page()
            await page.set_content(PAGE)
            pages.append(page)
        scrolling, clicking = pages
        await scrolling.mouse.move(190, 140)
        await scrolling.evaluate(RECORD)
        wheel = asyncio.create_task(scrolling.mouse.wheel(0, 20000))
        await asyncio.sleep(0.3)
        await clicking.mouse.click(190, 140)
        finished_first = wheel.done()
        await wheel
        events = await scrolling.evaluate("window.__events")
        return finished_first, [e[5] for e in events if e[0] == "wheel"]


def main() -> int:
    with hidden_display("1920x1080"):
        binary = resolve_binary()
        got = probe(binary, "linux", (("one", 100), ("three", 300)))
        wheel_finished_first, contended = asyncio.run(contended_wheel(binary))
    failures = []
    line = got["line"]
    if line < 8:
        failures.append(f"scrollByLines(1) moved the window {line} px: the line height could not be read")
    if wheel_finished_first:
        failures.append("a click in another context waited for a long wheel to finish")
    if any(b - a < 10 for a, b in zip(contended, contended[1:])):
        failures.append("a click in another context bunched a long wheel's notches under 10 ms apart")
    for name, notches in (("one", 1), ("three", 3)):
        events, scrolled = got[name]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        if shape != notch(line) * notches:
            failures.append(f"mouse.wheel ({name}) delivered {shape}, stock {notch(line) * notches}")
        if scrolled != 6 * line * notches:
            failures.append(f"mouse.wheel ({name}) scrolled {scrolled} px, stock {6 * line * notches} (six {line} px lines)")
        stamps = [e[5] for e in events if e[0] == "wheel"]
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        if any(g < 10 for g in gaps):
            failures.append(f"mouse.wheel ({name}) notches {gaps} ms apart: no wheel turns that fast")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: mouse.wheel turns notches as a wheel does in stock ({line} px lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
