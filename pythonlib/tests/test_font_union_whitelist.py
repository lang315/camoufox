"""The launch font whitelist must be the union of every bundled OS font set,
not just the target OS's set.

font-hijacker.patch writes the launch `fonts` list into font.system.whitelist,
and upstream ApplyWhitelist() deletes every family outside it from
mFontFamilies at startup. Narrowing that list to one OS is what made a
per-context setFontList() unable to widen back (#44): the families were
already gone. `fonts:whitelist` carries the union so all bundled families
survive startup; `fonts` itself must stay this profile's random per-OS subset
so every fallback path still narrows to a plausible list instead of reporting
all 732 bundled families (a list no real machine has).
"""

def test_launch_whitelist_is_the_union_not_one_os():
    from camoufox.utils import _launch_font_whitelist
    import json, pathlib
    fonts = json.loads((pathlib.Path(__file__).parents[1] /
                        "camoufox" / "fonts.json").read_text())
    got = set(_launch_font_whitelist())
    # and `fonts` must NOT have been widened along with it
    from camoufox.fingerprints import _generate_random_font_subset
    subset = _generate_random_font_subset("windows")
    assert len(subset) < 732, "the per-profile `fonts` subset must stay a subset"
    assert len(got) == 732, f"expected the 732-family union, got {len(got)}"
    for os_key in ("win", "mac", "lin"):
        missing = set(fonts[os_key]) - got
        assert not missing, f"{os_key} families absent from the launch whitelist: {sorted(missing)[:5]}"
