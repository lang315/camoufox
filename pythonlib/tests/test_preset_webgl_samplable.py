"""#169: every preset get_random_preset can draw must launch.

A preset whose WebGL pair is not in the WebGL database makes launch_options
raise `No WebGL data found for vendor ...`, so drawing it at random turns
`fingerprint_preset=True` into an intermittent crash.
"""

from unittest import mock

import pytest

from camoufox import fingerprints
from camoufox.webgl.sample import has_webgl

OS_CODE = {"windows": "win", "macos": "mac", "linux": "lin"}


@pytest.mark.parametrize("os_name", sorted(OS_CODE))
def test_every_drawable_preset_has_a_samplable_webgl_pair(os_name):
    drawn = []
    with mock.patch.object(fingerprints, "choice", side_effect=lambda c: drawn.extend(c) or c[0]):
        fingerprints.get_random_preset(os=os_name)
    assert drawn, f"no {os_name} presets drawable"
    bad = [p["webgl"] for p in drawn
           if p.get("webgl", {}).get("unmaskedVendor")
           and not has_webgl(OS_CODE[os_name], p["webgl"]["unmaskedVendor"], p["webgl"]["unmaskedRenderer"])]
    assert not bad, f"drawable {os_name} presets that launch_options cannot sample: {bad}"


def test_has_webgl_answers_both_ways():
    assert not has_webgl("win", "Mozilla", "Mozilla")
    pair = fingerprints.get_random_preset(os="windows")["webgl"]
    assert has_webgl("win", pair["unmaskedVendor"], pair["unmaskedRenderer"])
