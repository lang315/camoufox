"""
Regression test for daijro/camoufox#141: a small real monitor can produce a
Screen bound so tight that no fingerprint fits it. fpgen raises InvalidConstraints;
generate_fingerprint() must retry once without the bound instead of crashing
launch_options().
"""
import pytest

from camoufox import fingerprints as fp_module
from camoufox.fingerprints import Screen, generate_fingerprint

TIGHT_SCREEN = Screen(max_width=100, max_height=100)


def test_generate_fingerprint_falls_back_when_screen_constraint_too_tight():
    """The real-world repro: a bound no fingerprint fits must not crash."""
    fp = generate_fingerprint(screen=TIGHT_SCREEN, os='linux')
    assert fp['screen']['width'] > 0
    assert fp['screen']['height'] > 0


class InvalidConstraints(Exception):
    """Named like fpgen's, which is matched by class name."""


def test_retries_exactly_once_without_screen(monkeypatch):
    calls = []

    class Fake:
        def generate(self, **kwargs):
            calls.append('screen.width' in kwargs)
            if 'screen.width' in kwargs:
                raise InvalidConstraints('no fingerprint fits')
            return {'sentinel': True}

    monkeypatch.setattr(fp_module, '_generator', lambda: Fake())
    assert generate_fingerprint(screen=TIGHT_SCREEN, os='linux') == {'sentinel': True}
    assert calls == [True, False]  # first with the bound, retry without it


def test_reraises_when_there_is_no_screen_bound_to_drop(monkeypatch):
    class Fake:
        def generate(self, **kwargs):
            raise InvalidConstraints('boom')

    monkeypatch.setattr(fp_module, '_generator', lambda: Fake())
    with pytest.raises(InvalidConstraints):
        generate_fingerprint(os='linux')
