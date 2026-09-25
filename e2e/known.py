"""Findings this suite has made and filed.

A known red reports as KNOWN #issue instead of failing the gate, and is never
hidden: it prints on every run. Each entry is scoped to the hosts it was
measured on, so a platform nobody has measured still fails loudly. A strict
entry must keep failing; when its check passes the test fails with "fixed?",
so the entry is removed the day the bug is.
"""

import platform
import re

HOST = platform.system()

# (test node id regex, check text prefix, issue, strict, hosts measured on)
CHECKS = [
    (r"test_02_fingerprint\.py::test_(fingerprint_is_coherent\[(pkg|pw|go)-(windows|linux)\]"
     r"|locale_option_reaches_navigator_and_intl\[(pkg|pw)\])",
     # 0 of 8 README-path launches were monospaced per spoof, but one full-suite
     # run drew a preset that was: rare passes, so not strict.
     "monospace_is_monospace: monospace ", 162, False, {"Darwin"}),
    (r"test_02_fingerprint\.py::test_fingerprint_is_coherent\[(pkg|pw|go)-linux\]",
     "fonts_measurable: fallback floors", 162, False, {"Darwin"}),
    # Windows host (runs 36094067838, 36114027483): every driver collapses under the
    # macos and linux spoofs; the windows spoof is fine.
    (r"test_02_fingerprint\.py::test_fingerprint_is_coherent\[(pkg|pw|go)-(macos|linux)\]",
     "monospace_is_monospace: monospace ", 162, True, {"Windows"}),
    (r"test_02_fingerprint\.py::test_fingerprint_is_coherent\[(pkg|pw|go)-linux\]",
     "fonts_measurable: fallback floors", 162, True, {"Windows"}),
    # Windows host (run 36114027483): goapi's linux spoof exposes the host's Microsoft voices.
    (r"test_02_fingerprint\.py::test_fingerprint_is_coherent\[go-linux\]",
     "voices_no_foreign_os: ", 166, True, {"Windows"}),
    # Linux host (CI run 36038692790): only goapi collapses the generics, under every spoof.
    (r"test_02_fingerprint\.py::test_fingerprint_is_coherent\[go-",
     "monospace_is_monospace: monospace ", 162, True, {"Linux"}),
    (r"test_02_fingerprint\.py::test_fingerprint_is_coherent\[go-",
     "fonts_measurable: fallback floors", 162, True, {"Linux"}),
    (r"test_03_network\.py::test_webrtc_does_not_reveal_lan_address\[(pkg|pw)\]",
     "no LAN address", 163, True, {"Darwin", "Linux", "Windows"}),
    (r"test_03_network\.py::test_webrtc_does_not_reveal_lan_address\[(pkg|pw)\]",
     "the configured WebRTC IP appears", 163, True, {"Darwin", "Linux", "Windows"}),
    # Depends on which presets the launch and the context draw: intermittent, so not strict.
    (r"test_02_fingerprint\.py::test_new_context_fingerprint_is_coherent\[pkg-",
     "screen_contains_viewport: screen", 164, False, {"Darwin", "Linux", "Windows"}),
    # Bare Playwright's default 1280x720 viewport against a spoofed screen or window smaller
    # than it (Linux gate run 36131893534: outer 960x525 inner 1280x720).
    (r"test_02_fingerprint\.py::test_(fingerprint_is_coherent|locale_option_reaches_navigator_and_intl)\[pw-",
     "screen_contains_viewport: screen", 164, False, {"Darwin", "Linux"}),
    (r"test_02_fingerprint\.py::test_(fingerprint_is_coherent|locale_option_reaches_navigator_and_intl)\[go",
     "screen_contains_viewport: screen", 166, False, {"Darwin", "Linux", "Windows"}),
    # Timing: depends on how soon the first read lands.
    (r"test_05_contexts\.py::test_new_context_gives_each_context_its_own_identity\[pkg\]",
     "two pages of one context agree", 165, False, {"Darwin", "Linux"}),
]

# Findings that surface as an exception: (node id regex, issue, hosts, exception, strict).
RAISES = [
    (r"test_04_automation\.py::test_upload_and_download\[go\]", 166, {"Darwin", "Linux", "Windows"}, RuntimeError, True),
    (r"test_03_network\.py::test_proxy\[go-socks5\]", 166, {"Darwin", "Linux", "Windows"}, RuntimeError, True),
    # Intermittent: stalled at context 4 or 9 in two Linux runs, never on macOS.
    (r"test_08_lifecycle\.py::test_fifty_contexts_in_a_row\[(pkg|pw)\]", 171, {"Linux"}, AssertionError, False),
]


def for_check(nodeid: str, what: str):
    for pattern, prefix, issue, strict, hosts in CHECKS:
        if HOST in hosts and re.search(pattern, nodeid) and what.startswith(prefix):
            return issue, strict
    return None


def for_raise(nodeid: str):
    for pattern, issue, hosts, exc, strict in RAISES:
        if HOST in hosts and re.search(pattern, nodeid):
            return issue, exc, strict
    return None
