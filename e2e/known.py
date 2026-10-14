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
CHECKS = []

# Findings that surface as an exception: (node id regex, issue, hosts, exception, strict).
RAISES = []


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
