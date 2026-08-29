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


def test_user_passed_fonts_survive_the_whitelist():
    # `fonts=` is documented as families installed on the SYSTEM, so they are
    # not in the bundled union. A bundled-only whitelist would have
    # ApplyWhitelist() delete exactly what the caller asked for.
    from camoufox.utils import _resolve_font_whitelist

    wl = set(_resolve_font_whitelist(["Wingdings 3", "My Private Font"], False))
    assert {"Wingdings 3", "My Private Font"} <= wl
    assert len(wl) > 732, "the bundled union must still be there too"


def test_custom_fonts_only_keeps_the_whitelist_exact():
    # custom_fonts_only means OS-specific system fonts are not passed. Widening
    # past the caller's list would let a host family that happens to share a
    # bundled name survive -- the opposite of the flag.
    from camoufox.utils import _resolve_font_whitelist

    assert _resolve_font_whitelist(["My Private Font"], True) == ["My Private Font"]


def test_no_requested_fonts_is_just_the_union():
    from camoufox.utils import _resolve_font_whitelist

    assert len(_resolve_font_whitelist([], False)) == 732
