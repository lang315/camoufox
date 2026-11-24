"""driven-wheel-notches-macos.py derives its expectations from the line height the page reports (#461).

Firefox rounds a line to whole pixels for the events and scrolls its exact height, so a
page whose line is 16.5 px gets 17 in every event and 16.5 px a line. The line heights are
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
    # The three turns of the guard (16, 100 and 1000 px): each one event of round(px / 16) lines.
    turns = {"slow": [1], "turn": [6], "long": [63]}
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


NOTCHES = Path(__file__).resolve().parents[2] / "browser/tests/playwright/patches/driven-wheel-notches.py"


@pytest.fixture(scope="module")
def notch_guard():
    sys.path.insert(0, str(NOTCHES.parent))
    spec = importlib.util.spec_from_file_location("driven_wheel_notches", NOTCHES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def notch_reading(line, rounded):
    """driven-wheel-notches.py's turns of 1, 3 and 1 notches: a notch is six lines of deltaY, three of the
    legacy events, and scrolls six lines. The 19.5 px line is the local Retina Mac reading in #461."""
    got = {"step": 3 * line, "arrow": ""}
    for name, n in (("one", 1), ("three", 3), ("short", 1)):
        events = [["wheel", 1, 0, 6 * n, -120 * n, 1234], ["DOMMouseScroll", 3 * n], ["MozMousePixelScroll", 3 * rounded * n]]
        got[name] = (events, 6 * line * n)
    return got


def test_the_notch_guard_passes_a_line_of_nineteen_and_a_half_pixels(notch_guard):
    assert notch_guard.notch_failures(notch_reading(19.5, 20)) == []


def test_the_notch_guard_still_passes_a_whole_pixel_line(notch_guard):
    assert notch_guard.notch_failures(notch_reading(20, 20)) == []


def test_the_notch_guard_fails_events_that_do_not_round_the_line(notch_guard):
    assert notch_guard.notch_failures(notch_reading(19.5, 19.5))


def test_the_notch_guard_fails_a_scroll_other_than_six_of_the_pages_lines(notch_guard):
    got = notch_reading(19.5, 20)
    got["one"] = (got["one"][0], 120)
    assert any("scrolled 120 px, stock 117.0" in f for f in notch_guard.notch_failures(got))


def test_a_turn_split_over_several_events_fails(guard):
    got = reading(17, 17)
    got["turn"] = (delivered([1, 3, 2], 17), 17 * 6)
    assert any("one event of 6 lines" in f for f in guard.mac_failures(got))
