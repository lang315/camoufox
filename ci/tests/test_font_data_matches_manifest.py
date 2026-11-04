"""fonts.json and essential-fonts.json against the manifest they are generated from (#400).

Fork-only, like test_font_units.py. browser/scripts/gen-fonts-json.py writes both files from the
pinned font bundle and scripts/data/font-manifests.json, and regenerating needs the 843 MB
bundle, so no test here can regenerate. These checks need only the manifest: a name the manifest
no longer lists, or a floor entry that is not common to every base, means the files were not
regenerated after the manifest or the generator changed. #400 found 29 localized "System Font"
names in fonts.json[mac] that c27396c3 had removed from the manifest.
"""

import importlib.util
import json

import pytest

from ci._util import REPO_ROOT

SCRIPTS = REPO_ROOT / "browser/scripts"
PACKAGE = REPO_ROOT / "python/src/camoufox"
OSES = ["win", "mac", "lin"]


@pytest.fixture(scope="module")
def gen():
    import sys

    sys.path.insert(0, str(SCRIPTS))  # gen-fonts-json imports its sibling _font_bundle
    try:
        spec = importlib.util.spec_from_file_location("gen_fonts_json", SCRIPTS / "gen-fonts-json.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(SCRIPTS))
    return mod


@pytest.fixture(scope="module")
def manifest():
    return json.loads((SCRIPTS / "data/font-manifests.json").read_text(encoding="utf-8"))


def load(name):
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("os_key", OSES)
def test_fonts_json_names_only_families_the_generator_can_report(gen, manifest, os_key):
    wanted = gen.manifest_names(manifest, os_key) | set(gen.MARKER_FONTS[os_key])
    wanted |= set(gen.ALIASES[os_key]) | set(gen.REPORTABLE_EXTRA[os_key])
    stale = sorted(set(load("fonts.json")[os_key]) - wanted)
    assert not stale, (
        f"fonts.json[{os_key}] names {len(stale)} families the manifest does not list, e.g. {stale[:3]}; "
        "regenerate it: python3 browser/scripts/gen-fonts-json.py --print-bases, and refresh the goapi copies"
    )


@pytest.mark.parametrize("os_key", OSES)
def test_the_essential_floor_is_common_to_every_base_or_an_alias_of_such_a_family(gen, manifest, os_key):
    bases = [set(b["fonts"]) for b in manifest[os_key]["bases"].values() if b["fonts"] and not b.get("deferred")]
    common = set.intersection(*bases)
    allowed = common | {name for name, target in gen.ALIASES[os_key].items() if target in common}
    essential = set(load("essential-fonts.json")[os_key])
    extra = sorted(essential - allowed)
    assert not extra, (
        f"essential-fonts.json[{os_key}] holds {len(extra)} families that are not in every {os_key} base and are not "
        f"aliases of one, e.g. {extra[:3]}; regenerate it: python3 browser/scripts/gen-fonts-json.py --print-bases"
    )
    assert essential <= set(load("fonts.json")[os_key]), f"essential-fonts.json[{os_key}] names a family fonts.json does not"
