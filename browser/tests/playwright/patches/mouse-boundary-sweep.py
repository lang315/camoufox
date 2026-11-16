"""
Sweep the viewport boundary for coordinates that never reach the renderer.

This replaces hand-picked edge targets, which are what let four deadlocks
through. Each of the earlier tests probed the coordinates that had just been
found broken, so the next variant was always outside the list:

    humanize-edge-deadlock.py   probes the right and bottom edges only, so the
                                near edge (#751) passed it cleanly
    humanize-mouse-trajectory.py  pins os="linux", the one spoofed OS whose
                                chrome offset is immune to #751

The failure they all share: a synthesized event that hit-tests outside the
content widget fires as an exit event rather than eMouseMove, no
juggler-mouse-event-hit-renderer ack is produced, and -- because dispatch is
serialized on activateAndRun()'s process-global chain -- that one missing ack
wedges every later input event in the process. See docs/input-dispatch.md.

Rather than guess which coordinates do that, sweep the ring:

    x in {0, 1, w/2, w-2, w-1}  x  y in {0, 1, h/2, h-2, h-1}

across every spoofed OS (the chrome offset that decides #751 is a function of
it: windows 51.4, macos 53.1, linux 56.5) and with humanize both off and on,
at the default prefs and with text scaled to 105%. The scale is the other
half of the rounding: the widget hit-tests whole device pixels, and text at
105% on a display at ratio 1 gives the chrome 57 app units to one (1.0526 per
CSS pixel), so a point snapped onto whole CSS pixels can still round onto the
device row that holds the content's edge, which is chrome (#451). Measured on
a macOS host, content top 84.95: relative y == 0 went out at CSS 85, device
row 89 against an edge at 89.42, and the page got a mouseout at y == 0 after
a 5s ack wait. The chrome's scale is the identity's devicePixelRatio times the
text scale, so that arm pins the ratio: a drawn 1.5 gives 38 app units, where
the same snap happened to land inside.

Each point must be *delivered*, not merely survived: the page has to observe a
mousemove. A point that is dropped without hanging is still a bug -- it is the
"click did nothing" half of #752 -- and asserting only "did not time out" would
miss it.

This test depends on the ack backstop (MouseDispatch kAckDeadlineMs) to run at
all. Without it the first undelivered coordinate wedges the browser and the
sweep dies there, reporting one point instead of the whole failing set.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python3 browser/tests/playwright/patches/mouse-boundary-sweep.py

What PASS means: every ring coordinate, on every spoofed OS, humanized and not,
at both text scales, was acked and seen by the page; and input is still live at
the end of each run.
"""

import asyncio
import sys

from camoufox.async_api import AsyncCamoufox
from helpers import launch_kwargs

SPOOFED_OSES = ["windows", "macos", "linux"]
SCALES = ({}, {"firefox_user_prefs": {"ui.textScaleFactor": 105},
               "config": {"window.devicePixelRatio": 1}, "i_know_what_im_doing": True})
# Well inside the viewport, so every dispatched point is a real displacement.
INTERIOR = (0.34, 0.34)
# Per-point ceiling. Comfortably above the 5s ack deadline, so a dropped point
# shows up as "not delivered" with a fast return rather than as a timeout here.
POINT_TIMEOUT_S = 25

RECORDER = "window.__moves=0;addEventListener('mousemove',()=>window.__moves++)"


def _ring(w, h):
    xs = [0, 1, w // 2, w - 2, w - 1]
    ys = [0, 1, h // 2, h - 2, h - 1]
    return [(x, y) for y in ys for x in xs]


async def _sweep(spoofed_os, humanize, scale) -> list:
    """Returns the coordinates that did not reach the renderer."""
    undelivered = []
    async with AsyncCamoufox(**launch_kwargs(os=spoofed_os, humanize=humanize, **scale)) as browser:
        page = await browser.new_page()
        await page.set_content('<body style="margin:0;height:1600px"></body>')
        await page.evaluate(RECORDER)
        vp = await page.evaluate("({w:innerWidth,h:innerHeight})")
        w, h = vp["w"], vp["h"]
        home = (int(w * INTERIOR[0]), int(h * INTERIOR[1]))
        points = _ring(w, h)
        print(f"  [{spoofed_os}, humanize={humanize}, {scale.get('firefox_user_prefs', 'default prefs')}] {w}x{h}: "
              f"{len(points)} ring points", flush=True)

        for x, y in points:
            await asyncio.wait_for(page.mouse.move(*home), timeout=POINT_TIMEOUT_S)
            before = await page.evaluate("window.__moves")
            try:
                await asyncio.wait_for(page.mouse.move(x, y), timeout=POINT_TIMEOUT_S)
            except asyncio.TimeoutError:
                undelivered.append(((x, y), "hung -- the ack backstop did not fire"))
                # The chain is wedged; nothing after this can run.
                return undelivered
            after = await asyncio.wait_for(
                page.evaluate("window.__moves"), timeout=POINT_TIMEOUT_S)
            if after == before:
                undelivered.append(((x, y), "dispatched, but the page saw no mousemove"))

        # Prove the chain is not poisoned rather than trusting the absence of a
        # timeout above.
        try:
            await asyncio.wait_for(page.mouse.move(*home), timeout=POINT_TIMEOUT_S)
            await asyncio.wait_for(page.mouse.click(*home), timeout=POINT_TIMEOUT_S)
        except asyncio.TimeoutError:
            undelivered.append((home, "input dead after the sweep"))
    return undelivered


async def main() -> int:
    print("\n=== viewport boundary sweep ===")
    failures = []
    for spoofed_os in SPOOFED_OSES:
        for humanize in (False, True):
            for scale in SCALES:
                bad = await _sweep(spoofed_os, humanize, scale)
                for point, why in bad:
                    failures.append((spoofed_os, humanize, scale, point, why))
                    print(f"    FAIL {point}  {why}", flush=True)
                if not bad:
                    print("    ok", flush=True)

    if failures:
        print(f"\n  {len(failures)} coordinate(s) did not reach the renderer.\n"
              "  Every one of these wedges the process-global activation chain on a\n"
              "  build without the ack backstop. Fix the conversion in\n"
              "  additions/juggler/input/MouseDispatch.js -- see docs/input-dispatch.md.\n")
        return 1

    print("\n  PASS: every ring coordinate acked and observed, on every spoofed OS and text scale\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
