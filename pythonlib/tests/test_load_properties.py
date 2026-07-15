"""
Tests for camoufox.utils._load_properties path resolution.

Regression for daijro/camoufox#210: when an explicit executable_path is
given on macOS, properties.json lives in the .app bundle's
Contents/Resources, not next to the binary in Contents/MacOS.

Run with:
    cd pythonlib && python -m pytest tests/test_load_properties.py -v
"""

import os
import sys

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path  # noqa: E402

from camoufox.utils import _load_properties  # noqa: E402

PROPS = b'[{"property": "test:key", "type": "str"}]'


def _write(p: Path, data: bytes = PROPS) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app bundle layout")
def test_macos_bundle_resolves_properties_from_resources(tmp_path):
    # Layout: Camoufox.app/Contents/{MacOS/camoufox, Resources/properties.json}
    app = tmp_path / "Camoufox.app" / "Contents"
    exe = app / "MacOS" / "camoufox"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")  # fake binary
    _write(app / "Resources" / "properties.json")

    result = _load_properties(path=exe)
    assert result == {"test:key": "str"}


def test_sibling_properties_still_used(tmp_path):
    # Linux/Windows flat layout: properties.json next to the binary.
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    _write(tmp_path / "properties.json")

    result = _load_properties(path=exe)
    assert result == {"test:key": "str"}
