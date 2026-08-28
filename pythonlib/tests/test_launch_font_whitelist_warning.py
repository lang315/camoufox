"""NewContext must warn when the launch font whitelist excludes a context's fonts.

The launch-level font list becomes a process-wide whitelist:
gfxPlatformFontList's constructor writes it to font.system.whitelist and
ApplyWhitelist() then deletes every other family from mFontFamilies. A
per-context setFontList() runs later and can only narrow what survived, so a
family the launch config dropped can never be restored by a context (#44).

An earlier version of this warning was reverted because it claimed fonts had
"no per-context override" -- false, setFontList exists and is called. The
mechanism is the whitelist deleting families before the setter ever runs, and
these tests pin that distinction: the warning fires on excluded fonts and stays
silent when the launch list covers them.
"""

import json
import warnings

import pytest

from camoufox.utils import attach_launch_fonts, warn_fonts_excluded_by_launch


class FakeBrowser:
    """Stands in for a Playwright Browser, which accepts attributes."""


def _from_options(fonts):
    """A launch_options()-shaped dict carrying a chunked CAMOU_CONFIG."""
    blob = json.dumps({"fonts": fonts} if fonts is not None else {})
    return {"env": {"CAMOU_CONFIG_1": blob}}


def test_warns_naming_the_fonts_the_launch_list_dropped():
    b = attach_launch_fonts(FakeBrowser(), _from_options(["Segoe UI", "Tahoma"]))
    with pytest.warns(UserWarning) as rec:
        warn_fonts_excluded_by_launch(b, ["Helvetica Neue", "PingFang HK", "Tahoma"])
    msg = str(rec[0].message)
    assert "Helvetica Neue" in msg and "PingFang HK" in msg
    # Tahoma survives the whitelist, so it is not part of the complaint.
    assert "Tahoma" not in msg.split(":", 1)[1].split(".")[0]


def test_silent_when_the_launch_list_covers_the_context():
    b = attach_launch_fonts(FakeBrowser(), _from_options(["Geneva", "Helvetica Neue"]))
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes a failure
        warn_fonts_excluded_by_launch(b, ["Geneva"])


def test_silent_when_the_launch_config_sets_no_fonts():
    # No whitelist is installed, so nothing was deleted and the setter works.
    b = attach_launch_fonts(FakeBrowser(), _from_options(None))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_fonts_excluded_by_launch(b, ["Helvetica Neue"])


def test_silent_for_a_browser_that_never_went_through_attach():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_fonts_excluded_by_launch(FakeBrowser(), ["Helvetica Neue"])


def test_long_lists_are_truncated_rather_than_dumped():
    b = attach_launch_fonts(FakeBrowser(), _from_options(["Tahoma"]))
    asked = [f"Font {i}" for i in range(9)]
    with pytest.warns(UserWarning) as rec:
        warn_fonts_excluded_by_launch(b, asked)
    msg = str(rec[0].message)
    assert "9 of this context's fonts" in msg
    assert "and 4 more" in msg
