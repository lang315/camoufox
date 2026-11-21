"""
mouse.wheel() reaches the page as a mouse wheel does in stock macOS Firefox.

macOS differs. A person's notched mouse on stock 159.0 gives one line a slow
notch: deltaY 1, wheelDeltaY -48, DOMMouseScroll detail 1, MozMousePixelScroll
16. A faster turn gives single events of more lines, with those values in proportion.
A line is the scroller's line height, so the 16 and 48 follow the page's font, and the guard reads the line from
what an arrow key scrolls: a fractional line (16.5 px) gives events of the rounded line (17) and a scroll of its own height.

One mouse.wheel(dx, dy) call is one wheel event. On a macOS identity it is one event of round(px / 16)
lines, at least one. This is the macOS arm of driven-wheel-notches.py, apart from it because a
macOS identity cannot be drawn on every host: a hosted Windows runner's 1366x768 display fits none and neither
does a hosted macOS runner's 1280x720 (fpgen: RestrictiveConstraints, runs 42902541346 and 42923629488). The runner
counts it not applicable on both, so it runs on Linux, on Xvfb at 1920x1080.

The scroller is driven-wheel-notches.py's, 1200 px tall. Gecko limits one wheel scroll to a page of the
scroller unless the user allows more (dom/events/EventStateManager.cpp:3779-3797): the scroll port less the
smaller of a tenth of it and two lines. A 200 px scroller cut a 12-line event at a 17 px line to 180 px (1040
of 1071 px over a turn, as that cap predicts), and the longest turn here is one event of 63 lines: 1071 px at
the 17 px line this page gives, over the 1066 px cap of a 1100 px scroller.

    python browser/tests/playwright/patches/driven-wheel-notches-macos.py
"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from helpers import hidden_display, resolve_binary  # noqa: E402

spec = importlib.util.spec_from_file_location("driven_wheel_notches", HERE / "driven-wheel-notches.py")
notches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notches)


def mac_failures(got):
    failures = []
    step = got["step"]
    if not step:
        failures.append(f"ArrowDown did not finish scrolling ({got['arrow']})")
    elif step * 2 % 3 or not 24 <= step <= 120:
        failures.append(f"an arrow key scrolled the scroller {step} px: three lines of 8 to 40 px, in half pixels, were expected")
    # The page's line may be fractional (16.5 px, #461). Gecko rounds it to whole pixels for the events and
    # scrolls its exact height.
    line = step / 3
    rounded = int(line + 0.5)
    for name, lines in (("slow", 1), ("turn", 6), ("long", 63)):
        events, scrolled = got[name]
        wheels = [e[3] for e in events if e[0] == "wheel"]
        expected = [
            part
            for dy in wheels
            for part in (["wheel", 1, 0, dy, -3 * rounded * dy], ["DOMMouseScroll", dy], ["MozMousePixelScroll", rounded * dy])
        ]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        if shape != expected:
            failures.append(f"macOS mouse.wheel ({name}) delivered {shape}, expected {expected}")
        if wheels != [lines]:
            failures.append(f"macOS mouse.wheel ({name}) sent lines {wheels}: one event of {lines} lines")
        if scrolled != line * lines:
            failures.append(f"macOS mouse.wheel ({name}) scrolled {scrolled} px, expected {line * lines}")
    return failures


def main() -> int:
    with hidden_display("1920x1080"):
        mac = notches.probe(resolve_binary(), "macos", (("slow", 16), ("turn", 100), ("long", 1000)))
    failures = mac_failures(mac)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: mouse.wheel turns notches on a macOS identity as a wheel does in stock macOS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
