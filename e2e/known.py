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
    # Windows host on Firefox 156 (e2e run 38274480396): a macos or linux identity renders
    # Windows-only marker families, in every driver.
    (r"test_02_fingerprint\.py::test_(new_context_)?fingerprint_is_coherent\[(pkg|pw|go)-(macos|linux)\]",
     "fonts_no_foreign_os: ", 193, True, {"Windows"}),
    # Depends on which presets the launch and the context draw: intermittent, so not strict.
    (r"test_02_fingerprint\.py::test_new_context_fingerprint_is_coherent\[pkg-",
     "screen_contains_viewport: screen", 164, False, {"Darwin", "Linux", "Windows"}),
    # Timing: depends on how soon the first read lands.
    (r"test_05_contexts\.py::test_new_context_gives_each_context_its_own_identity\[pkg\]",
     "two pages of one context agree", 165, False, {"Darwin", "Linux"}),
    # goapi has no rendering plan (#196): a launch on another OS still sends canvas:seed and
    # gets no RFP placeholder, so its canvas reads the same twice. The same missing plan means
    # goapi, unlike the Python and TypeScript launchers, still allows a cross-OS context on a
    # native-OS launch. Read from the code, not yet measured on a browser: strict, so a host
    # where it passes says so.
    (r"test_05_contexts\.py::test_a_covered_launch_reads_the_canvas_placeholder\[go\]",
     "canvas readback is the placeholder: ", 196, True, {"Darwin", "Linux", "Windows"}),
]

# Findings that surface as an exception: (node id regex, issue, hosts, exception, strict).
RAISES = [
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
