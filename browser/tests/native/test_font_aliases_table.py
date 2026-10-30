"""The Linux alias table is what the staged bundle's fontconfig produces (#325).

FontAliasesLinux.hpp is generated from browser/bundle/fontconfig/linux/fonts.conf
and the Linux font groups. A conf edit, a bundle that gains or loses a family,
or a fonts.json change that moves a name makes it stale, and a stale table sends
a Linux claim on Windows or macOS to the wrong face. This test needs the built
browser's directory (fonts/, fontconfig/linux/) and fontconfig's command-line
tools; it fails, never skips, when either is missing.
"""

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
