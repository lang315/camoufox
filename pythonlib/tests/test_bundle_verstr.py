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
import warnings

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from camoufox import utils as camoufox_utils  # noqa: E402
from camoufox import pkgman  # noqa: E402
from camoufox.pkgman import Version  # noqa: E402
from camoufox.utils import _bundle_verstr  # noqa: E402
from camoufox.utils import _bundle_version  # noqa: E402

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
    from camoufox import DefaultAddons
    from camoufox import utils as camoufox_utils

    def _boom():
        raise _ManagedInstallConsulted

    monkeypatch.setattr(camoufox_utils, "installed_verstr", _boom)

    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(APP_INI)

    try:
        # exclude_addons=[UBO]: without it, launch_options() reaches
        # add_default_addons() -> maybe_download_addons(), which downloads
        # uBlock Origin from addons.mozilla.org before hitting the guarded
        # line. If that download raises (no network, DNS failure, sandboxed
        # CI), the except Exception below swallows it and the test passes
        # without ever exercising the read under test. DefaultAddons has one
        # member, so excluding it makes the addon step a no-op: no network
        # call, no write under the addons dir.
        camoufox_utils.launch_options(
            executable_path=str(exe), headless=True, exclude_addons=[DefaultAddons.UBO]
        )
    except _ManagedInstallConsulted:
        raise AssertionError(
            "launch_options() still reads the managed install when the caller "
            "supplied executable_path (#97)"
        ) from None
    except Exception:
        pass  # any other failure is downstream of the read under test


# Not unit-covered here: the managed-launch direction through launch_options()
# (no executable_path). Driving it re-enters the managed-fetch path and would
# create ~/Library/Caches/camoufox on every run. The half that needs no drive,
# _bundle_verstr(None) is None, is test_no_path_returns_none above.


# --- _bundle_version: both halves of `Version=`, on the axis Version compares --

def test_bundle_version_reads_build_tag_and_firefox_version(tmp_path):
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(APP_INI)

    v = _bundle_version(exe)
    assert v is not None
    assert v.build == "beta.31"
    assert v.version == "152.0.4"
    # The comparison Version actually makes is on the build tag.
    assert v >= Version(build="beta.30")
    assert v > Version(build="beta.29")


def test_bundle_version_macos_app_layout(tmp_path):
    contents = tmp_path / "Camoufox.app" / "Contents"
    exe = contents / "MacOS" / "camoufox"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (contents / "Resources").mkdir(parents=True)
    (contents / "Resources" / "application.ini").write_bytes(APP_INI)

    v = _bundle_version(exe)
    assert v is not None and v.build == "beta.31"


def test_bundle_version_without_build_tag_returns_none(tmp_path):
    # A `Version=` with no `-<build>` half cannot be placed on the floor axis.
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(b"[App]\nVersion=152.0.4\n")

    assert _bundle_version(exe) is None


def test_bundle_version_empty_build_token_returns_none(tmp_path):
    # Version.__post_init__ does ord(x[0]) per dot-separated build token, so a
    # trailing dot ("beta.") raises IndexError inside the constructor. The
    # never-raises contract must absorb that, not leak it out of the warning.
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(b"[App]\nVersion=152.0.4-beta.\n")

    assert _bundle_version(exe) is None


def test_bundle_version_missing_file_returns_none(tmp_path):
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    assert _bundle_version(exe) is None


def test_bundle_version_none_path_returns_none():
    assert _bundle_version(None) is None


# --- warn_if_executable_predates_playwright: now reachable for packages -------

def _pin_playwright(monkeypatch, major_minor):
    """effective_version_min() reads the resolved Playwright; pin it so the floor
    is deterministic regardless of what is installed on the host."""
    monkeypatch.setattr(pkgman, "_resolved_playwright_version", lambda: major_minor)


def test_warning_fires_for_a_package_below_the_floor(tmp_path, monkeypatch):
    """#102: packages ship no version.json, so this warning never fired for any
    real user. With application.ini as the source it fires when it should."""
    _pin_playwright(monkeypatch, (1, 61))  # floor becomes beta.30
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(
        b"[App]\nVersion=152.0.0-beta.29\n"
    )

    with pytest.warns(RuntimeWarning, match=r"is beta\.29, but Playwright .* needs at least beta\.30"):
        camoufox_utils.warn_if_executable_predates_playwright(exe)


def test_warning_silent_for_a_package_at_or_above_the_floor(tmp_path, monkeypatch):
    _pin_playwright(monkeypatch, (1, 61))
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(APP_INI)  # beta.31

    # Silence must mean "parsed and at/above the floor", not "failed to parse
    # and returned early" -- those print identically without this line.
    assert _bundle_version(exe) is not None
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        camoufox_utils.warn_if_executable_predates_playwright(exe)
    assert [w for w in rec if "needs at least" in str(w.message)] == []


def test_warning_silent_when_playwright_is_below_the_pairing(tmp_path, monkeypatch):
    # Playwright < 1.61 never sends the fields beta.29 rejects; no floor is raised.
    _pin_playwright(monkeypatch, (1, 60))
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "application.ini").write_bytes(b"[App]\nVersion=152.0.0-beta.29\n")

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        camoufox_utils.warn_if_executable_predates_playwright(exe)
    assert [w for w in rec if "needs at least" in str(w.message)] == []


def test_version_json_still_answers_when_no_application_ini(tmp_path, monkeypatch):
    # An unpackaged objdir build with version.json keeps the pre-#102 path.
    _pin_playwright(monkeypatch, (1, 61))
    exe = tmp_path / "camoufox"
    exe.write_bytes(b"")
    (tmp_path / "version.json").write_bytes(b'{"version": "152.0.0", "release": "beta.29"}')

    with pytest.warns(RuntimeWarning, match=r"is beta\.29"):
        camoufox_utils.warn_if_executable_predates_playwright(exe)


_REAL_BINARY = "/tmp/cf97/cf/Camoufox.app/Contents/MacOS/camoufox"


@pytest.mark.skipif(not os.path.exists(_REAL_BINARY), reason="extracted package not present")
def test_real_package_does_not_warn(monkeypatch):
    """The regression that matters: if parsing the beta suffix misreads a
    current package as below the floor, every executable_path user gets a
    spurious warning on every launch. Read against a real extracted build."""
    _pin_playwright(monkeypatch, (1, 61))
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        camoufox_utils.warn_if_executable_predates_playwright(_REAL_BINARY)
    assert [w for w in rec if "needs at least" in str(w.message)] == []
