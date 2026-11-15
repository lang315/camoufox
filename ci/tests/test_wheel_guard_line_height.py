"""driven-wheel-notches-macos.py derives its expectations from the line height the page reports (#461).

Firefox rounds a line to whole pixels for the events and scrolls its exact height, so a
page whose line is 16.5 px gets 17 in every event and 16.5 px a line. The readings are
those of Tests run 43681967153, job 132718067021.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "browser/tests/playwright/patches/driven-wheel-notches-macos.py"


@pytest.fixture(scope="module")
def guard():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("driven_wheel_notches_macos", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def delivered(wheels, line):
    """The events one `mouse.wheel` of `wheels` lines per event gives: a timestamp ends each wheel event."""
    return [
        part
        for dy in wheels
        for part in (["wheel", 1, 0, dy, -3 * line * dy, 1234], ["DOMMouseScroll", dy], ["MozMousePixelScroll", line * dy])
    ]


def reading(line, rounded):
    # The three turns of the guard: the lines each event carries, as the red job delivered them.
    turns = {"slow": [1], "turn": [1, 3, 2], "long": [1, 4, 5, 7, 8, 10, 11, 12, 5]}
    got = {"step": 3 * line, "arrow": ""}
    for name, wheels in turns.items():
        got[name] = (delivered(wheels, rounded), line * sum(wheels))
    return got


def test_a_page_whose_line_is_sixteen_and_a_half_pixels_passes(guard):
    assert guard.mac_failures(reading(16.5, 17)) == []


def test_a_page_whose_line_is_whole_pixels_still_passes(guard):
    assert guard.mac_failures(reading(17, 17)) == []


def test_a_line_that_is_not_rounded_to_whole_pixels_in_the_events_fails(guard):
    assert guard.mac_failures(reading(16.5, 16.5))


def test_a_scroll_other_than_the_pages_own_line_fails(guard):
    got = reading(16.5, 17)
    got["slow"] = (got["slow"][0], 17)
    assert any("scrolled 17 px, expected 16.5" in f for f in guard.mac_failures(got))
