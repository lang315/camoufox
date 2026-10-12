"""#162 (B): name the spoofed OS's generic families in prefs."""

import os
import sys

import orjson
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from camoufox import utils  # noqa: E402
from test_launch_geometry import host  # noqa: E402

FONTS = orjson.loads(open(os.path.join(os.path.dirname(utils.__file__), "fonts.json"), "rb").read())


@pytest.mark.parametrize("os_key", ["win", "mac", "lin"])
def test_every_named_family_ships_in_that_os_list(os_key):
    for pref, value in utils.generic_font_prefs(os_key).items():
        for fam in (f.strip() for f in value.split(",")):
            assert fam in FONTS[os_key], f"{os_key} {pref} names {fam!r}, which {os_key}'s list lacks"


@pytest.mark.parametrize("spoof,mono", [("windows", "Consolas, Courier New"), ("macos", "Menlo, Courier New"), ("linux", "Cousine")])
def test_launch_options_sets_the_spoofed_generics(spoof, mono):
    with host(None):
        prefs = utils.launch_options(os=spoof, i_know_what_im_doing=True)["firefox_user_prefs"]
    assert prefs["font.name-list.monospace.x-western"] == mono


def test_the_test_hook_turns_them_off(monkeypatch):
    monkeypatch.setenv("CAMOUFOX_NO_GENERIC_PREFS", "1")
    with host(None):
        prefs = utils.launch_options(os="windows", i_know_what_im_doing=True)["firefox_user_prefs"]
    assert not any(k.startswith("font.name-list.") for k in prefs)


def test_a_caller_pref_wins():
    with host(None):
        prefs = utils.launch_options(os="windows", i_know_what_im_doing=True,
                                     firefox_user_prefs={"font.name-list.monospace.x-western": "Courier New"})["firefox_user_prefs"]
    assert prefs["font.name-list.monospace.x-western"] == "Courier New"
