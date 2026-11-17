"""Keep a pytest suite off the developer's real camoufox cache (#279, #489).

Shared by the Python suite (python/tests/conftest.py) and the native suite
(browser/tests/native/conftest.py). camoufox computes its cache directories when
it is first imported, from the platform's cache location (HOME on macOS,
XDG_CACHE_HOME on Linux, LOCALAPPDATA on Windows), so `isolate()` has to run
before that import.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT: Path


def isolate() -> Path:
    """Point every platform's cache location at a fresh temp root, and return it."""
    global ROOT
    ROOT = Path(tempfile.mkdtemp(prefix="camoufox-pytest-")).resolve()
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(ROOT)
    os.environ["LOCALAPPDATA"] = str(ROOT / "AppData" / "Local")
    os.environ["XDG_CACHE_HOME"] = str(ROOT / ".cache")
    return ROOT


def cache_paths_outside(root: Path) -> list:
    """Every camoufox cache constant that resolves outside `root`.

    A cache constant is a module-level Path in the package that has a
    "camoufox" component and is not the package's own source tree, so a new one
    is covered without being listed here.
    """
    from camoufox import pkgman

    package_dir = Path(pkgman.__file__).resolve().parent
    outside = []
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("camoufox") or module is None:
            continue
        for attr, value in vars(module).items():
            if not isinstance(value, Path) or "camoufox" not in value.parts:
                continue
            resolved = value.resolve()
            if not (resolved.is_relative_to(package_dir) or resolved.is_relative_to(root)):
                outside.append(f"{name}.{attr} = {value}")
    return outside


def check_session_start() -> None:
    """Fail before any test when a cache constant escaped the root."""
    outside = cache_paths_outside(ROOT)
    if outside:
        raise pytest.UsageError(f"cache paths outside the test root {ROOT}: " + "; ".join(outside))


def remove_root() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)
