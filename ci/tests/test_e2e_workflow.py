"""Fork-only checks on .github/workflows/e2e.yml (#283).

A leg with no browser to test must not exist: it would conclude `success`
having tested nothing. The `targets` job decides which legs run, from the
artifacts of the build run or the assets of the release.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap

from ci._util import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "e2e.yml"


def _targets(names: list[str], *, run_id="", release="v1"):
    """Run the `targets` job's own resolver on `names`; return the process and
    the target names it chose."""
    text = WORKFLOW.read_text(encoding="utf-8")
    job = text.split("\n  targets:\n", 1)[1].split("\n  e2e:\n", 1)[0]
    script = job.split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    out = REPO_ROOT / ".ci-work" / "e2e-targets-output"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "NAMES": "\n".join(names),
        "RUN_ID": run_id,
        "RELEASE": release if not run_id else "",
        "GITHUB_OUTPUT": str(out),
    }
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], env=env, capture_output=True, text=True
    )
    written = out.read_text(encoding="utf-8")
    out.unlink()
    if not written:
        return proc, []
    matrix = json.loads(written.split("matrix=", 1)[1])
    return proc, [leg["target"] for leg in matrix["include"]]


def test_a_mac_only_build_runs_the_mac_leg_alone():
    proc, chosen = _targets(["CamoufoxBuilds-macos-arm64"], run_id="1")
    assert proc.returncode == 0, proc.stderr
    assert chosen == ["macos-arm64"]


def test_a_windows_only_build_runs_the_windows_leg_alone():
    proc, chosen = _targets(["CamoufoxBuilds-windows-x86_64"], run_id="1")
    assert proc.returncode == 0, proc.stderr
    assert chosen == ["windows-x86_64"]


def test_a_full_build_runs_all_three_legs():
    names = [
        "CamoufoxBuilds-linux-x86_64",
        "CamoufoxBuilds-macos-arm64",
        "CamoufoxBuilds-windows-x86_64",
        "CamoufoxBuilds-windows-i686",
    ]
    proc, chosen = _targets(names, run_id="1")
    assert proc.returncode == 0, proc.stderr
    assert sorted(chosen) == ["linux-x86_64", "macos-arm64", "windows-x86_64"]


def test_a_release_without_a_linux_build_runs_two_legs():
    names = [
        "camoufox-158.0-beta.33-mac.arm64.zip",
        "camoufox-158.0-beta.33-win.x86_64.zip",
        "SHA256SUMS",
    ]
    proc, chosen = _targets(names)
    assert proc.returncode == 0, proc.stderr
    assert sorted(chosen) == ["macos-arm64", "windows-x86_64"]


def test_an_input_that_holds_no_browser_fails_loudly():
    proc, chosen = _targets(["Some-other-artifact"], run_id="42")
    assert proc.returncode == 1
    assert chosen == []
    assert "::error::" in proc.stdout + proc.stderr
    assert "42" in proc.stdout + proc.stderr


def test_the_skip_mechanism_is_gone():
    assert "E2E_SKIP" not in WORKFLOW.read_text(encoding="utf-8")


def test_util_unpacks_a_zip_and_prints_the_browser_path(tmp_path):
    """The observer and goapi steps need the browser's path, which the journeys'
    `binary` fixture only computes inside pytest: `e2e/util.py --zip` prints it."""
    import zipfile

    archive = tmp_path / "e2e-unpack-test.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("camoufox/application.ini", "[App]\nBuildID=1\n")
        z.writestr("camoufox/camoufox-bin", "")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "e2e" / "util.py"), "--zip", str(archive)],
        capture_output=True, text=True,
    )
    unpacked = REPO_ROOT / ".ci-work" / "e2e" / "unpacked" / archive.stem
    try:
        assert proc.returncode == 0, proc.stderr
        printed = proc.stdout.strip().splitlines()[-1]
        assert printed.endswith("camoufox-bin") and os.path.exists(printed), proc.stdout
    finally:
        shutil.rmtree(unpacked, ignore_errors=True)


def _swallowed_substitutions(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines()
            if re.search(r'echo\b.*\$\(.*GITHUB_ENV', ln)]


def test_no_step_writes_a_command_substitution_straight_into_the_env_file():
    """`echo "X=$(cmd)" >> "$GITHUB_ENV"` exits 0 when `cmd` fails, so the step
    passes with X empty: a macOS unpack that hit a 403 went on to run the gates
    with no browser (D run 40841174691). Assign first, then echo."""
    assert _swallowed_substitutions(WORKFLOW.read_text(encoding="utf-8")) == []
    old = 'run: echo "CAMOUFOX_BINARY=$(python e2e/util.py $E2E_BROWSER)" >> "$GITHUB_ENV"'
    assert _swallowed_substitutions(old), "the check must catch the pattern it exists for"
