"""
The #44 contract guard (.github/workflows/smoke.yml, "#44 contract guard" step)
reds a run in which all three contexts report ONE renderer that is not the
launch's, calling it a cross-context leak. That verdict is only sound because a
windows context can never draw a renderer a mac or linux context can draw:
webgl/webgl_data.db's win pool shares no renderer string with its mac or lin
pools. That is a property of a binary data file, not of code, so it is pinned
here -- regenerating the db in a way that breaks it fails this test instead of
turning the guard's leak verdict into a false red.

Run with:
    cd pythonlib && python -m pytest tests/test_webgl_pool_disjoint.py -v
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_DB = os.path.join(os.path.dirname(__file__), "..", "camoufox", "webgl", "webgl_data.db")


def _pools():
    con = sqlite3.connect(_DB)
    rows = con.execute("SELECT renderer, win, mac, lin FROM webgl_fingerprints").fetchall()
    con.close()
    pools = {"win": set(), "mac": set(), "lin": set()}
    for renderer, win, mac, lin in rows:
        for key, weight in (("win", win), ("mac", mac), ("lin", lin)):
            if float(weight) > 0:
                pools[key].add(renderer)
    return pools


def test_windows_renderer_pool_is_disjoint_from_mac_and_linux():
    pools = _pools()
    assert pools["win"] and pools["mac"] and pools["lin"], "a pool is empty -- db unreadable?"
    assert pools["win"] & pools["mac"] == set(), sorted(pools["win"] & pools["mac"])
    assert pools["win"] & pools["lin"] == set(), sorted(pools["win"] & pools["lin"])


def test_mac_and_linux_pools_do_overlap():
    # Documents the OTHER half of the guard's reasoning: mac/lin DO share
    # strings, which is why a two-context collision is treated as a benign
    # preset draw and not a verdict. If this ever becomes empty, the guard's
    # ::notice:: path is dead and its comment about collision rates is stale.
    pools = _pools()
    assert pools["mac"] & pools["lin"], "mac/lin pools no longer overlap"
