"""
Regression test for daijro/camoufox#141: a small real monitor can produce a
Screen(max_width=..., max_height=...) constraint so tight that browserforge
1.2.4 raises ValueError("No headers based on this input can be generated...")
instead of relaxing it -- crashing launch_options() outright. generate_fingerprint()
must retry once without the screen constraint (and warn) instead of propagating
the crash.

Run with:
    cd camoufox && PYTHONPATH=pythonlib python3 -m pytest pythonlib/tests/test_screen_constraint_fallback.py -v
"""
import os
import sys
import warnings

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from browserforge.fingerprints import Screen  # noqa: E402

from camoufox import fingerprints as fp_module  # noqa: E402
from camoufox.fingerprints import generate_fingerprint  # noqa: E402

# Empirically reproduces browserforge 1.2.4's
# ValueError("No headers based on this input can be generated...") 100% of the time
# (a small real monitor, per #141).
TIGHT_SCREEN = Screen(max_width=800, max_height=600)


def test_generate_fingerprint_falls_back_when_screen_constraint_too_tight():
    """The real-world repro: a tight Screen constraint must no longer crash."""
    with pytest.warns(RuntimeWarning, match="screen"):
        fp = generate_fingerprint(screen=TIGHT_SCREEN, os='linux')
    assert fp is not None
    assert fp.screen.width > 0
    assert fp.screen.height > 0


def test_generate_fingerprint_unconstrained_still_works_silently():
    # Sanity: normal (no screen constraint) generation must still succeed with no warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fp = generate_fingerprint(os='linux')
    assert fp is not None


def test_retries_exactly_once_without_screen_on_valueerror(monkeypatch):
    """Precisely pins down the wrapper's retry mechanics using a fake generator,
    independent of browserforge's actual constraint-solving behavior."""
    calls = []

    def _fake_generate(**kwargs):
        calls.append(kwargs.get('screen'))
        if kwargs.get('screen') is not None:
            raise ValueError("No headers based on this input can be generated.")
        return "SENTINEL_FINGERPRINT"

    monkeypatch.setattr(fp_module.FP_GENERATOR, 'generate', _fake_generate)

    with pytest.warns(RuntimeWarning, match="screen"):
        result = generate_fingerprint(screen=TIGHT_SCREEN, os='linux')

    assert result == "SENTINEL_FINGERPRINT"
    assert calls == [TIGHT_SCREEN, None]  # first call with the constraint, retry without it


def test_reraises_valueerror_when_no_screen_constraint_to_drop(monkeypatch):
    """If there's no `screen` in the config, there's nothing to retry without --
    the ValueError must propagate rather than being silently swallowed."""

    def _always_raises(**kwargs):
        raise ValueError("boom - unrelated failure")

    monkeypatch.setattr(fp_module.FP_GENERATOR, 'generate', _always_raises)

    with pytest.raises(ValueError, match="boom"):
        generate_fingerprint(os='linux')
