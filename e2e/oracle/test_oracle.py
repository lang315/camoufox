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
              "rendered": {"windows": ["Segoe UI"], "macos": [], "linux": []},
              "mono": {"i": 193.0, "m": 193.0}, "sans": {"i": 71.0, "m": 267.0}},
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


def test_proportional_monospace_is_caught():
    fp = copy.deepcopy(FP)
    fp["fonts"]["mono"] = {"i": 71.67, "m": 267.17}
    assert coherence.monospace_is_monospace(fp, REQ, "windows")[0] is False


def test_font_markers_are_exclusive():
    m = docs.font_markers()
    assert all(m.values()), m
    for a in m:
        for b in m:
            assert a == b or not set(m[a]) & set(m[b])


def test_known_finding_reports_known_and_strict_entry_flags_a_fix(monkeypatch):
    import known
    from util import Checks

    monkeypatch.setattr(known, "HOST", "Darwin")
    node = "journeys/test_03_network.py::test_webrtc_does_not_reveal_lan_address[pw]"
    red = Checks(node)
    red(False, "no LAN address ['10.0.0.2'] in candidates or SDP")
    assert red.failed == []
    fixed = Checks(node)  # #163 is strict
    fixed(True, "no LAN address ['10.0.0.2'] in candidates or SDP")
    assert fixed.failed and "#163" in fixed.failed[0]
    other = Checks(node)
    other(False, "the STUN server was asked")
    assert other.failed == ["the STUN server was asked"]
    monkeypatch.setattr(known, "HOST", "Plan9")  # a host nobody has measured
    unmeasured = Checks(node)
    unmeasured(False, "no LAN address ['10.0.0.2'] in candidates or SDP")
    assert unmeasured.failed, "a host nobody measured must fail loudly"


def test_a_negative_control_is_never_matched_against_the_ledger(monkeypatch):
    # The #166 voices entry's prefix also matched its always-green control, which then
    # read as "FIXED?" (e2e run 36124566821).
    import known
    from util import Checks

    monkeypatch.setattr(known, "HOST", "Windows")
    node = "journeys/test_02_fingerprint.py::test_fingerprint_is_coherent[go-linux]"
    c = Checks(node)
    c(True, "voices_no_foreign_os: its negative control went red (else VACUOUS)", ledger=False)
    assert c.failed == []
    c(False, "voices_no_foreign_os: its negative control went red (else VACUOUS)", ledger=False)
    assert c.failed, "a control that did not go red fails even under a ledgered check"
