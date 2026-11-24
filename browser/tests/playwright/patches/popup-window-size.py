r"""
A window a page opens gets the size and position its window.open() features
ask for, and every window reports its own content size; the window automation
opens reports the identity's position.

CamoufoxWindow.sys.mjs resizes a new browser window to the identity's outer
size and holds that size through startup. It did that to every window,
including one a page opened, so

    window.open('about:blank', '', 'width=400,height=300')

came back as large as the main window, where stock gives a 400x300 content area.
Only the windows automation opens are the identity's; a window with an opener
is sized as stock sizes it.

Position the same way: window.screenX/screenY answered the identity's
position for every window, so the popup below read the main window's
position instead of the left=37,top=41 it asked for. Now the first window is
moved to the identity's position and every window reports where it is.
A headless launch and a headful one (Xvfb with no window manager on Linux, the host's
desktop elsewhere) both report the identity's position.

innerWidth and innerHeight returned the identity's window.innerWidth and
innerHeight in every window, so that popup and every iframe reported the main
window's content size, larger than the popup's own outerWidth (#963). The
identity here carries both sizes, and a 300x150 iframe must report 300x150.

The popup's size is read several times across the startup hold, so a late
resize to the identity's size is caught too.

The identity is fitted to the monitor the guard runs on (a hosted Windows
monitor is 1024 px wide and a hosted macOS one 1280), because the launcher
refuses a headful window the monitor cannot hold (on macOS, one taller than the
visible frame between the menu bar and the Dock, #514). The subject is the same at any
size above the popup's: the popup asks for 400x300, and a popup that took the
identity's size would read that size instead.

    python browser/tests/playwright/patches/popup-window-size.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

REQUESTED = [400, 300]
FRAME = [300, 150]
PLACED = [37, 41]
CLAIMED = [123, 45]
WIDE = [1366, 728]  # the window this guard asks for where the monitor holds it
CHROME_HEIGHT = 85  # outerHeight - innerHeight of that window


def identity(monitor):
    """The identity's screen and window, no larger than the monitor.

    The launcher refuses a headful window the monitor cannot hold, and clamps a
    position that would put the window off the screen, so the screen is the
    monitor's (at most 1920x1080) and the window leaves room for the claimed
    position. Nothing below depends on the window being 1366 wide: the popup
    asks for REQUESTED, and the main window only has to be larger than that and
    answer with the identity's own sizes. On macOS the window is also no taller
    than the visible frame, which macOS shrinks a taller window to (#514)."""
    from camoufox.display import visible_height

    width = min(1920, monitor.max_width)
    height = min(1080, monitor.max_height)
    outer = [min(WIDE[0], width - CLAIMED[0]),
             min(WIDE[1], height - CLAIMED[1], visible_height() or monitor.max_height)]
    return {
        "window.screenX": CLAIMED[0],
        "window.screenY": CLAIMED[1],
        "screen.width": width,
        "screen.height": height,
        "screen.availLeft": 0,
        "screen.availTop": 0,
        "screen.availWidth": width,
        "screen.availHeight": height,
        "window.innerWidth": outer[0],
        "window.innerHeight": outer[1] - CHROME_HEIGHT,
        "window.outerWidth": outer[0],
        "window.outerHeight": outer[1],
    }


FRAME_SIZE = f"""() => new Promise(resolve => {{
  const frame = document.createElement('iframe');
  frame.style = 'border:0;width:{FRAME[0]}px;height:{FRAME[1]}px';
  frame.onload = () => resolve([frame.contentWindow.innerWidth, frame.contentWindow.innerHeight]);
  document.body.appendChild(frame);
}})"""


async def probe(binary, config):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, executable_path=str(binary), config=config,
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        main_size = await page.evaluate("() => [innerWidth, innerHeight, outerWidth, outerHeight]")
        main_pos = await page.evaluate("() => [screenX, screenY]")
        frame_size = await page.evaluate(FRAME_SIZE)
        async with page.context.expect_page() as popup_info:
            await page.evaluate(
                f"() => {{ window.open('about:blank', '', "
                f"'width={REQUESTED[0]},height={REQUESTED[1]},"
                f"left={PLACED[0]},top={PLACED[1]}'); }}"
            )
        popup = await popup_info.value
        await popup.wait_for_load_state()
        readings, positions = [], []
        for _ in range(6):
            readings.append(await popup.evaluate("() => [innerWidth, innerHeight]"))
            positions.append(await popup.evaluate("() => [screenX, screenY]"))
            await asyncio.sleep(0.5)
        return main_size, main_pos, frame_size, readings, positions


async def headful_position(binary, config):
    """The identity's position on a window with a real X display (an Xvfb with no
    window manager on Linux, the host's desktop elsewhere)."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=False, executable_path=str(binary), config=config,
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        await asyncio.sleep(2)
        return await page.evaluate("() => [screenX, screenY]")


def main() -> int:
    binary = resolve_binary()
    with hidden_display():
        # The monitor the headful launch is checked against, read as the launcher reads it.
        from camoufox.utils import get_screen_cons

        monitor = get_screen_cons(headless=False)
        if monitor is None:
            raise SystemExit("FAIL: SETUP-INVALID, the launcher cannot read this display's size")
        config = identity(monitor)
        # A main window no larger than the popup's request would make a popup that
        # took the identity's size read as the size it asked for.
        if config["window.innerWidth"] <= REQUESTED[0] or config["window.innerHeight"] <= REQUESTED[1]:
            raise SystemExit(f"FAIL: SETUP-INVALID, a {monitor.max_width}x{monitor.max_height} monitor leaves a "
                             f"{config['window.innerWidth']}x{config['window.innerHeight']} content area, "
                             f"not larger than the popup's {REQUESTED}")
        main_size, main_pos, frame_size, readings, positions = asyncio.run(probe(binary, config))
        headful_pos = asyncio.run(headful_position(binary, config))
    print(f"monitor {monitor.max_width}x{monitor.max_height}, identity window {config['window.outerWidth']}x"
          f"{config['window.outerHeight']}")
    print(f"headful main window at {headful_pos}")
    print(f"main window inner and outer {main_size} at {main_pos}, iframe inner {frame_size}, "
          f"popup inner {readings} at {positions}")
    failures = []
    if main_size[:2] != [config["window.innerWidth"], config["window.innerHeight"]]:
        failures.append(f"the main window's content area {main_size[:2]} is not the identity's")
    if frame_size != FRAME:
        failures.append(f"a {FRAME} iframe reports {frame_size}")
    if any(reading != REQUESTED for reading in readings):
        failures.append(f"the popup's content area is not the {REQUESTED} its features asked for")
    if main_pos != CLAIMED:
        failures.append(f"the headless main window is not at the identity's position {CLAIMED}")
    if headful_pos != CLAIMED:
        failures.append(f"the headful main window is at {headful_pos}, not the identity's position {CLAIMED}")
    if any(position != PLACED for position in positions):
        failures.append(f"the popup does not report the position {PLACED} its features asked for")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a page's popup keeps its requested size and position, and an iframe its own size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
