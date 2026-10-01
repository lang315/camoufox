"""#169: every preset get_random_preset can draw must launch.

A preset whose GPU fpgen has never seen Firefox report on its OS makes
launch_options raise `No recorded WebGL data for vendor ...`, so drawing it at random turns
`fingerprint_preset=True` into an intermittent crash.
"""

from unittest import mock

import pytest

from camoufox import fingerprints
from camoufox.webgl import firefox_gpus

OS_CODE = {"windows": "win", "macos": "mac", "linux": "lin"}


@pytest.mark.parametrize("os_name", sorted(OS_CODE))
def test_every_drawable_preset_has_a_samplable_webgl_pair(os_name):
    drawn = []
    with mock.patch.object(fingerprints, "choice", side_effect=lambda c: drawn.extend(c) or c[0]):
        fingerprints.get_random_preset(os=os_name)
    assert drawn, f"no {os_name} presets drawable"
    bad = [p["webgl"] for p in drawn
           if p.get("webgl", {}).get("unmaskedVendor")
           and (p["webgl"]["unmaskedVendor"], p["webgl"]["unmaskedRenderer"]) not in firefox_gpus(OS_CODE[os_name])]
    assert not bad, f"drawable {os_name} presets that launch_options cannot sample: {bad}"


def test_webgl_samplable_answers_both_ways():
    assert not fingerprints._webgl_samplable(
        "windows", {"webgl": {"unmaskedVendor": "No Vendor", "unmaskedRenderer": "No GPU"}})
    pair = fingerprints.get_random_preset(os="windows")["webgl"]
    assert fingerprints._webgl_samplable("windows", {"webgl": pair})
