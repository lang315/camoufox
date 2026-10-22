"""ci/apt_install.py: the one place CI installs runtime packages with apt (#275).

A runner's apt-get update once printed nothing for an hour, under -qq, until the
job's time limit cancelled it. The script bounds each apt command and names the
one that ran out of time.
"""

import os
import re
import subprocess
import sys

from ci._util import REPO_ROOT

SCRIPT = REPO_ROOT / "ci" / "apt_install.py"
WORKFLOWS = REPO_ROOT / ".github"


def _run(tmp_path, update="exit 0", install="exit 0", limit="900"):
    """Run the script with a stand-in `sudo` and `apt-get`; return the process and the apt-get calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "apt-get").write_text(
        f'#!/bin/sh\necho "$*" >> "{calls}"\n'
        f'case "$1" in update) {update};; install) {install};; esac\n'
    )
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "xvfb", "zstd"],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "APT_TIMEOUT": limit},
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, calls.read_text().splitlines() if calls.exists() else []


def test_updates_then_installs_the_packages_it_is_given(tmp_path):
    proc, calls = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert calls == ["update", "install -y --no-install-recommends xvfb zstd"]


def test_a_stalled_update_fails_the_step_and_names_the_command(tmp_path):
    proc, calls = _run(tmp_path, update="exec sleep 30", limit="1")
    assert proc.returncode != 0
    assert "apt-get update" in proc.stdout + proc.stderr
    assert "1s" in proc.stdout + proc.stderr
    assert calls == ["update"], "the install must not run after a stalled update"


def test_a_stalled_install_fails_the_step_and_names_the_command(tmp_path):
    proc, _ = _run(tmp_path, install="exec sleep 30", limit="1")
    assert proc.returncode != 0
    assert "apt-get install" in proc.stdout + proc.stderr


def test_a_failed_install_keeps_its_exit_code(tmp_path):
    proc, _ = _run(tmp_path, install="exit 100")
    assert proc.returncode == 100


def test_no_workflow_hides_the_progress_of_apt_get_update():
    """-qq printed nothing for the hour the step hung, so the log could not say
    which stage stalled. Every update prints its progress."""
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for path in [*WORKFLOWS.glob("workflows/*.yml"), *WORKFLOWS.glob("actions/*/action.yml")]
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"apt-get update\s+-qq", line)
    ]
    assert not offenders, offenders
