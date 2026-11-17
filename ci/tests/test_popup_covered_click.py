"""popup-covered-click moves where the panel is, and a dropped move is not a covered one (#469).

The guard used to move to a fixed point of the page, assuming the date picker covers it. A launch
whose window sits flush right on its screen has the panel pushed left of its input by the headless
screen's 1366 px edge (panel x 1092..1366, window at 1298), so that point was outside the panel and
the guard timed out. It also read a move Juggler never delivered (5 s ack deadline) as one a popup
took. The numbers are the red launch of Tests run 43906858431 (job 133441633590, launch 25).
"""

import importlib.util

import pytest

from ci._util import REPO_ROOT


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location(
        "popup_covered_click", REPO_ROOT / "browser/tests/playwright/patches/popup-covered-click.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Screen rects (x, y, width, height) of that launch: the picker, and the page's content area.
RED_PANEL = (1092, 154, 274, 303)
RED_CONTENT = (1298, 130, 1262, 1298)
# A launch whose window is at the screen's left edge: the panel is under its input.
GREEN_PANEL = (0, 107, 274, 303)
GREEN_CONTENT = (0, 85, 1920, 947)


def inside(rect, point):
    x, y, w, h = rect
    return x <= point[0] < x + w and y <= point[1] < y + h


@pytest.mark.parametrize("panel, content", [(RED_PANEL, RED_CONTENT), (GREEN_PANEL, GREEN_CONTENT)])
def test_the_point_is_in_the_panel_and_in_the_page(guard, panel, content):
    cx, cy = guard.covered_point(panel, content)
    screen = (content[0] + cx, content[1] + cy)
    assert inside(panel, screen) and inside(content, screen)


def test_the_old_fixed_point_is_outside_the_red_panel():
    # client (150, 90) in the red's window: the point the guard moved to before this fix.
    assert not inside(RED_PANEL, (RED_CONTENT[0] + 150, RED_CONTENT[1] + 90))


def test_a_panel_that_misses_the_page_has_no_point(guard):
    assert guard.covered_point((0, 0, 274, 100), (500, 500, 800, 600)) is None


def test_a_move_that_waited_out_the_ack_deadline_is_dropped_not_covered(guard):
    assert guard.move_verdict(took_s=5.01, page_saw=False) == "dropped"
    assert guard.move_verdict(took_s=0.02, page_saw=False) == "covered"
    assert guard.move_verdict(took_s=0.02, page_saw=True) == "reached the page"


def read(state, panel, content=(0, 85, 1280, 683)):
    return {"state": state, "panel": list(panel), "content": list(content)}


@pytest.mark.parametrize("seen", [
    None,
    read("showing", (0, 107, 274, 303)),
    read("open", (0, 0, 0, 0)),
    # Tests run 43947261469, job 133590159488, display arm: the read the guard took too early.
    read("open", (0, 0, 1, 1), (0, 85, 1280, 683)),
    # Run 43956846664, job 133617160042: 13 ms of 0.8 x 0.8 at the origin before the real rect.
    read("open", (0, 0, 0.8, 0.8), (0, 84.8, 1024, 723.2)),
])
def test_the_picker_is_not_there_until_it_covers_a_point_of_the_page(guard, seen):
    assert guard.open_point(seen) is None


def test_an_open_picker_that_covers_the_page_gives_its_point(guard):
    panel, content = (0, 107.2, 273.6, 302.4), (0, 84.8, 1024, 723.2)
    cx, cy = guard.open_point(read("open", panel, content))
    assert (cx, cy) == (137, 88)
    assert inside(panel, (content[0] + cx, content[1] + cy)) and inside(content, (content[0] + cx, content[1] + cy))
