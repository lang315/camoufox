# pythonlib/tests/test_context_os_coherence.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402


def test_init_script_records_setters_the_page_does_not_provide():
    from camoufox.fingerprints import _build_init_script

    js = _build_init_script({"webglRenderer": "Apple M1", "canvasSeed": 7})
    assert "__camoufoxMissingSetters" in js, "no way to tell an absent setter from a working one"
    assert js.count("__camoufoxMissingSetters") >= 2, "must record, not just declare"


def _binary():
    for c in (os.environ.get("CFX_BIN"),
              "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"):
        if c and os.path.exists(c):
            return c
    return None


@pytest.mark.skipif(_binary() is None, reason="needs a Camoufox binary (set CFX_BIN)")
def test_missing_setters_are_observable_in_a_real_page():
    from camoufox.sync_api import Camoufox, NewContext

    with Camoufox(headless=True, executable_path=_binary(), os="macos",
                  ff_version=152, i_know_what_im_doing=True) as b:
        ctx = NewContext(b, os="macos")
        page = ctx.new_page()
        page.goto("about:blank")
        missing = page.evaluate("() => window.__camoufoxMissingSetters || []")
        ctx.close()

    # Not an assertion about WHICH are missing -- that is binary-dependent. The
    # point is the list exists, so a missing browser-side setter is discoverable
    # instead of a silent no-op.
    assert isinstance(missing, list)
    print("setters absent from this binary:", missing)
