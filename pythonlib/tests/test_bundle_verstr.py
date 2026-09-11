"""
Tests for camoufox.utils._bundle_verstr.

Regression for lang315/camoufox#97: a caller-supplied executable_path used to
resolve its Firefox major through installed_verstr(), which reads the MANAGED
install and raises CamoufoxNotInstalled when there is none. The version is
available in the build's own bundle, in application.ini.

Run with:
    cd pythonlib && python -m pytest tests/test_bundle_verstr.py -v
"""

import os
import sys

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.utils import _bundle_verstr  # noqa: E402

APP_INI = b"""; This file is not used.
[App]
Vendor=Camoufox
Name=Camoufox
Version=152.0.4-beta.31
BuildID=20260911054553

[Gecko]
MinVersion=152.0.4
MaxVersion=152.0.4
"""


def test_flat_bundle_reads_sibling_application_ini(tmp_path):
    # Linux/Windows layout: application.ini next to the binary.
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(APP_INI)

    assert _bundle_verstr(exe) == "152"


def test_macos_app_bundle_reads_from_resources(tmp_path):
    # Camoufox.app/Contents/{MacOS/camoufox, Resources/application.ini}
    contents = tmp_path / "Camoufox.app" / "Contents"
    exe = contents / "MacOS" / "camoufox"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (contents / "Resources").mkdir(parents=True)
    (contents / "Resources" / "application.ini").write_bytes(APP_INI)

    assert _bundle_verstr(exe) == "152"


def test_missing_application_ini_returns_none(tmp_path):
    # An unpackaged objdir build tells us nothing; the caller falls back.
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")

    assert _bundle_verstr(exe) is None


def test_unreadable_application_ini_returns_none(tmp_path):
    """The never-raises contract covers a file that exists but cannot be read.

    A directory at the expected path raises IsADirectoryError -- an OSError
    subclass, the same branch a permissions failure takes. Preferred over
    chmod 000, which does nothing when the suite runs as root and which
    Windows does not enforce, either of which would need a platform skip.
    """
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").mkdir()

    assert _bundle_verstr(exe) is None


def test_unparsable_version_line_returns_none(tmp_path):
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(b"[App]\nVersion=notaversion\n")

    assert _bundle_verstr(exe) is None


def test_no_path_returns_none():
    # A managed launch passes no executable_path.
    assert _bundle_verstr(None) is None


def test_gecko_minversion_is_not_mistaken_for_the_app_version(tmp_path):
    # `[Gecko] MinVersion=` must not answer; only `[App] Version=` does.
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(
        b"[Gecko]\nMinVersion=99.0.0\nMaxVersion=99.0.0\n"
    )

    assert _bundle_verstr(exe) is None


class _ManagedInstallConsulted(Exception):
    """Raised in place of installed_verstr() to prove it was reached."""


def test_launch_options_does_not_consult_the_managed_install(tmp_path, monkeypatch):
    """#97: executable_path must not require `camoufox fetch`.

    installed_verstr() is replaced with a raiser -- which is what it does on a
    machine with no managed install. Reaching it AT ALL is the bug, so the
    assertion is on which exception escapes, not on a return value.

    launch_options() does a great deal after this read and may fail later for
    unrelated reasons; any exception that is not _ManagedInstallConsulted means
    the managed install was not consulted, which is what this test checks.
    """
    from camoufox import utils as camoufox_utils

    def _boom():
        raise _ManagedInstallConsulted

    monkeypatch.setattr(camoufox_utils, "installed_verstr", _boom)

    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(APP_INI)

    try:
        camoufox_utils.launch_options(executable_path=str(exe), headless=True)
    except _ManagedInstallConsulted:
        raise AssertionError(
            "launch_options() still reads the managed install when the caller "
            "supplied executable_path (#97)"
        ) from None
    except Exception:
        pass  # any other failure is downstream of the read under test


def test_managed_launch_still_resolves_through_installed_verstr(monkeypatch):
    """No executable_path -> _bundle_verstr declines and the fallback stands."""
    from camoufox import utils as camoufox_utils

    assert camoufox_utils._bundle_verstr(None) is None
