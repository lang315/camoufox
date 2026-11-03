"""The Linux alias table is what the staged bundle's fontconfig produces (#325).

FontAliasesLinux.hpp is generated from browser/bundle/fontconfig/linux/fonts.conf
and the Linux font groups. A conf edit, a bundle that gains or loses a family,
or a fonts.json change that moves a name makes it stale, and a stale table sends
a Linux claim on Windows or macOS to the wrong face. This test needs the built
browser's directory (fonts/, fontconfig/linux/) and fontconfig's command-line
tools; it fails, never skips, when either is missing.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_alias_table_matches_the_bundle(binary):
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "browser" / "scripts" / "gen-font-aliases.py"),
         "--bin-dir", str(binary.parent), "--check"],
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_header_carries_the_four_generic_chains():
    """The chains are what --check compares; this names them so a dropped one is a plain failure (#333)."""
    header = (REPO_ROOT / "browser" / "additions" / "camoucfg" / "FontAliasesLinux.hpp").read_text(encoding="utf-8")
    for name in ("Serif", "SansSerif", "Monospace", "Cursive"):
        match = re.search(rf"kCamouLinux{name}Chain\[\] = \{{(.*?)\}};", header)
        assert match, f"no {name} chain"
        families = re.findall(r'"([^"]+)"', match.group(1))
        assert 1 <= len(families) <= 3 and len(set(families)) == len(families), f"{name}: {families}"


def test_the_header_carries_the_lang_group_chains():
    """Every lang group the generator lists has four chains of faces, so a dropped group is a plain failure (#389)."""
    header = (REPO_ROOT / "browser" / "additions" / "camoucfg" / "FontAliasesLinux.hpp").read_text(encoding="utf-8")
    arrays = {n: re.findall(r'"([^"]+)"', body) for n, body in
              re.findall(r"static const char\* const (kCamouLinuxChain\d+)\[\] = \{(.*?)\};", header)}
    rows = re.findall(r'\{"([a-z-]+)", (kCamouLinuxChain\d+), (kCamouLinuxChain\d+), '
                      r'(kCamouLinuxChain\d+), (kCamouLinuxChain\d+)\},', header)
    assert [tag for tag, *_ in rows] == ["ja", "ko", "zh-cn", "zh-tw", "zh-hk", "ar"]
    for tag, *names in rows:
        for name in names:
            faces = arrays[name]
            assert 1 <= len(faces) <= 12 and len(set(faces)) == len(faces), f"{tag} {name}: {faces}"
