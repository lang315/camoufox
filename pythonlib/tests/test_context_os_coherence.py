# pythonlib/tests/test_context_os_coherence.py
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from camoufox import utils  # noqa: E402


def _opts(user_agent):
    """Shape launch_options returns: chunked CAMOU_CONFIG_<n> under env."""
    import orjson
    blob = orjson.dumps({"navigator.userAgent": user_agent}).decode()
    return {"env": {"CAMOU_CONFIG_1": blob}}


def test_launched_os_reads_mac_from_generated_options():
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0"
    assert utils.launched_os(_opts(ua)) == "mac"


def test_launched_os_reads_windows():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    assert utils.launched_os(_opts(ua)) == "win"


def test_launched_os_is_none_when_config_absent():
    assert utils.launched_os({"env": {}}) is None


def test_launched_os_tolerates_malformed_config_suffix():
    """A CAMOU_CONFIG_<n> key with a non-numeric suffix must not raise -- treated
    as nothing usable, same as an undecodable JSON blob a few lines below it."""
    assert utils.launched_os({"env": {"CAMOU_CONFIG_bad": '{"navigator.userAgent": "x"}'}}) is None


class _FakeBrowser:
    def __init__(self, launched):
        self._camoufox_os = launched


def test_warns_when_context_os_differs_from_launch_os():
    # Args are already the resolved short form ('mac'/'win'/'lin'), as produced
    # by determine_ua_os -- this is what NewContext now passes.
    with pytest.warns(RuntimeWarning, match="no per-context override"):
        utils._warn_os_mismatch(_FakeBrowser("win"), "mac")


def test_silent_when_context_os_matches_launch_os():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        utils._warn_os_mismatch(_FakeBrowser("mac"), "mac")


def test_silent_when_launch_os_unknown():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        utils._warn_os_mismatch(_FakeBrowser(None), "mac")


def test_warns_when_no_os_was_requested_but_resolved_os_differs():
    """The default call pattern: NewContext(browser) with no `os=` at all. The
    context still resolves to a concrete OS from its generated UA, and that
    resolved OS -- not the absent `os=` kwarg -- is what must be compared
    against the launch OS (issue #44's actual failure mode)."""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    resolved_os = utils.determine_ua_os(ua)  # 'win' -- the caller never chose this
    with pytest.warns(RuntimeWarning, match="no per-context override"):
        utils._warn_os_mismatch(_FakeBrowser("mac"), resolved_os)
