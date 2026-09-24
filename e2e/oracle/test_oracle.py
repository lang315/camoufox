"""Offline checks of the oracles themselves: no browser needed."""

import copy

import pytest

from oracle import coherence, docs

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
SNAP = {"ua": WINDOWS_UA, "platform": "Win32", "language": "en-US", "languages": ["en-US", "en"], "cores": 8, "tz": "Europe/Berlin"}
FP = {
    "main": SNAP,
    "intl": "en-US",
    "tz": {"tz": "Europe/Berlin", "offset": -120, "derived": -120},
    "screen": {"w": 1920, "h": 1080, "aw": 1920, "ah": 1040, "iw": 1280, "ih": 720, "ow": 1296, "oh": 800, "dpr": 1},
    "webdriver": False,
    "dedicated": dict(SNAP),
    "shared": dict(SNAP),
    "service": "error: TypeError",
    "fonts": {"floors": {"mono": 400.0, "serif": 350.0}, "valid": True,
              "rendered": {"windows": ["Segoe UI"], "macos": [], "linux": []}},
    "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, GeForce Direct3D11 vs_5_0 ps_5_0)"},
    "voices": [{"name": "Microsoft David", "uri": "urn:moz-tts:sapi:Microsoft David"}],
    "canvas": 123,
}
REQ = {"headers": [("Host", "x"), ("User-Agent", WINDOWS_UA), ("Accept-Language", "en-US,en;q=0.5")]}


def test_plausible_windows_browser_passes_every_rule():
    for name, ok, detail, red in coherence.evaluate(copy.deepcopy(FP), copy.deepcopy(REQ), "windows"):
        assert ok is True, (name, detail)
        assert red is True, f"{name}: negative control did not go red (VACUOUS)"


@pytest.mark.parametrize("key", sorted(docs.CLAIMS))
def test_every_documented_claim_is_still_documented(key):
    docs.cite(key)


def test_foreign_fonts_are_caught():
    fp = copy.deepcopy(FP)
    fp["fonts"]["rendered"]["macos"] = ["Helvetica Neue"]
    assert coherence.fonts_no_foreign_os(fp, REQ, "windows")[0] is False


def test_rule_without_os_is_not_applicable():
    assert coherence.os_is_requested(FP, REQ, None)[0] is None
