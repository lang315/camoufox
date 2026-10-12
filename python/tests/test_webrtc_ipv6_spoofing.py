"""
Regression test for daijro/camoufox#287: the per-context init script only ever
called window.setWebRTCIPv4(), even when the configured WebRTC IP was IPv6 --
so an IPv6 address was silently fed to the v4 setter and setWebRTCIPv6()
(implemented C++-side by patches/webrtc-ip-spoofing.patch) was never called.

Run with:
    cd camoufox && PYTHONPATH=pythonlib python3 -m pytest pythonlib/tests/test_webrtc_ipv6_spoofing.py -v
"""
import os
import sys

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import _build_init_script, generate_context_fingerprint  # noqa: E402

IPV6_ADDR = '2001:db8::1'
IPV4_ADDR = '203.0.113.5'


def test_ipv6_webrtc_ip_calls_v6_setter_not_v4():
    script = _build_init_script({'webrtcIP': IPV6_ADDR})
    assert 'setWebRTCIPv6("2001:db8::1")' in script
    assert 'setWebRTCIPv4' not in script


def test_ipv4_webrtc_ip_still_calls_v4_setter_not_v6():
    script = _build_init_script({'webrtcIP': IPV4_ADDR})
    assert f'setWebRTCIPv4("{IPV4_ADDR}")' in script
    assert 'setWebRTCIPv6' not in script


def test_no_webrtc_ip_clears_v4_setter_only():
    script = _build_init_script({})
    assert 'setWebRTCIPv4("")' in script
    assert 'setWebRTCIPv6' not in script


def test_generate_context_fingerprint_wires_ipv6_end_to_end():
    # End-to-end: the public per-context entry point must also route an IPv6
    # webrtc_ip to setWebRTCIPv6, not setWebRTCIPv4.
    fp = generate_context_fingerprint(os='linux', webrtc_ip=IPV6_ADDR)
    assert f'setWebRTCIPv6("{IPV6_ADDR}")' in fp['init_script']
    assert 'setWebRTCIPv4' not in fp['init_script']
