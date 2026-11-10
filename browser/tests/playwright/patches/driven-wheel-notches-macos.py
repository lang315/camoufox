"""
mouse.wheel() reaches the page as a mouse wheel does in stock macOS Firefox.

macOS differs. A person's notched mouse on stock 159.0 gives one line a slow
notch: deltaY 1, wheelDeltaY -48, DOMMouseScroll detail 1, MozMousePixelScroll
16. A faster turn starts at one line and grows, with those values in proportion.
A line is the scroller's line height, so the 16 and 48 follow the page's font.

Juggler turns 100 px into one notch, rounding, at least one; on a macOS identity it sends lines, which the
OS accelerates in a faster turn. This is the macOS arm of driven-wheel-notches.py, apart from it because a
macOS identity cannot be drawn on every host: a hosted Windows runner's 1366x768 display fits none
(fpgen: RestrictiveConstraints, run 42902541346). The runner counts it not applicable there, and it runs on
Linux (Xvfb) and on macOS.

The scroller is 600 px tall. Gecko limits one wheel scroll to a page of the scroller unless the
user allows more (dom/events/EventStateManager.cpp:3779-3797), and the longest turn here sends events
of up to 12 lines: 204 px at the 17 px line this page gives, which a 200 px scroller cut short (1016
to 1040 px of 1071 in five launches of this build, 999 to 1057 with a 16 px font page), where a
600 px one scrolled exactly 1071 in five of five. A 15 px line would give 180 px and not meet it.

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
    line = next(e[1] for e in got["slow"][0] if e[0] == "MozMousePixelScroll")
    for name, lines in (("slow", 1), ("turn", 6), ("long", 63)):
        events, scrolled = got[name]
        wheels = [e[3] for e in events if e[0] == "wheel"]
        expected = [
            part
            for dy in wheels
            for part in (["wheel", 1, 0, dy, -3 * line * dy], ["DOMMouseScroll", dy], ["MozMousePixelScroll", line * dy])
        ]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        if shape != expected:
            failures.append(f"macOS mouse.wheel ({name}) delivered {shape}, expected {expected}")
        if not wheels or wheels[0] != 1 or sum(wheels) != lines:
            failures.append(f"macOS mouse.wheel ({name}) sent lines {wheels}: a burst starts at 1 and totals {lines}")
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
