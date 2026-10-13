"""Fork-only checks on .github/workflows/tests.yml and build.yml.

Kept out of test_ci.py on purpose: that file is upstream's (daijro/camoufox),
and a fork-only assertion there would conflict with every future sync that
touches it.
"""

import pytest
import yaml

from ci._util import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
BUILD = WORKFLOW.with_name("build.yml")
GUARD = '"${{ github.repository }}" != "daijro/camoufox"'


def _scope_commands(text: str) -> str:
    """The shell of the `Does this change the browser?` step, comments dropped."""
    step = text.split("- name: Does this change the browser?", 1)[1].split("- name:", 1)[0]
    return "\n".join(
        line for line in step.splitlines() if not line.strip().startswith("#")
    )


def _guard_block(commands: str) -> list[str]:
    """The fork guard's own lines, from its `if` to its own `fi` -- bounded by
    the shell, not by a character count, so comment edits cannot move it."""
    lines = [l.strip() for l in commands.splitlines()]
    start = next(i for i, l in enumerate(lines) if GUARD in l)
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return lines[start:end]


def _check_fork_guard(commands: str) -> None:
    assert GUARD in commands, "the scope step has no fork guard"
    guard_at = commands.index(GUARD)
    assert guard_at < commands.index("git diff --name-only"), (
        "the fork guard runs after the changed-files check, which can already "
        "have chosen the fetch path"
    )
    block = _guard_block(commands)
    sets = [i for i, l in enumerate(block) if "browser_changed=true" in l]
    assert sets, "the fork guard does not set browser_changed=true"
    assert "exit 0" in block[sets[0]:], (
        "the fork guard does not exit after setting browser_changed=true, so the "
        "changed-files branch can overwrite it"
    )


def test_a_fork_never_grades_against_the_released_browser():
    """`camoufox fetch` resolves releases from python/src/camoufox/repos.yml,
    whose first entry is daijro/camoufox. On this fork the fetch tier would
    grade a driver-only pull request against upstream's browser, which carries
    none of the fork's patches -- a green about the wrong binary. Every run
    outside daijro/camoufox must take the build path, and must decide that
    before the changed-files classification can send it to fetch."""
    _check_fork_guard(_scope_commands(WORKFLOW.read_text(encoding="utf-8")))


def _drop_first_guard_line(text: str, line: str) -> str:
    """The workflow with the first `line` after the fork guard removed."""
    head, tail = text.split(GUARD, 1)
    lines = tail.splitlines(keepends=True)
    at = next(i for i, l in enumerate(lines) if l.strip() == line)
    return head + GUARD + "".join(lines[:at] + lines[at + 1 :])


@pytest.mark.parametrize("line", [
    "exit 0",
    'echo "browser_changed=true" >> "$GITHUB_OUTPUT"',
])
def test_the_fork_guard_check_catches_a_broken_guard(line):
    """Without its own `exit 0` the guard falls through to the changed-files
    branch, which can overwrite browser_changed=false for a driver-only pull
    request -- the #127 bug back. Without its own echo it sets nothing. Either
    must fail the check above, however the step's comments change (#137)."""
    broken = _drop_first_guard_line(WORKFLOW.read_text(encoding="utf-8"), line)
    with pytest.raises(AssertionError):
        _check_fork_guard(_scope_commands(broken))


# --- the install job on a fork -----------------------------------------------


def _job_block(text: str, job: str) -> str:
    """One top-level job's YAML, from its key to the next job's key."""
    head = f"\n  {job}:\n"
    body = text.split(head, 1)[1]
    return body.split("\n  # ----", 1)[0]


def _summary_required(repository: str) -> set:
    """Run the summary step's own `required=` assembly for `repository`."""
    import subprocess

    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index('required="pythonlib')
    end = text.index("python3 -m ci.summarize", start)
    block = (
        text[start:end]
        .replace("${{ needs.resolve.outputs.browser_changed }}", "true")
        .replace("${{ needs.resolve.outputs.has_sundial }}", "false")
        .replace("${{ github.repository }}", repository)
    )
    proc = subprocess.run(
        ["bash", "-c", block + '\necho "$required"'], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return set(proc.stdout.split())


def test_install_runs_only_on_daijro_camoufox():
    """ci/run_install.py pins the newest release on GITHUB_REPOSITORY whose tag
    matches `^v<ver>-<prefix>.<n>$` (ci/release.py). Fork tags carry a `-fork.N`
    suffix, so they never match and the job would fail every fork pull request."""
    install = _job_block(WORKFLOW.read_text(encoding="utf-8"), "install")
    assert "if: github.repository == 'daijro/camoufox'" in install


def test_install_is_required_on_daijro_and_not_on_a_fork():
    """A skipped job writes no result, so a required `install` would fail the
    summary on a fork; dropping it on daijro would silently stop requiring it."""
    assert "install" in _summary_required("daijro/camoufox")
    assert "install" not in _summary_required("lang315/camoufox")


def test_the_gate_lets_install_skip_on_a_fork_only():
    """The gate fails any skipped job that may_skip does not excuse."""
    gate = _job_block(WORKFLOW.read_text(encoding="utf-8"), "gate")
    assert '"install": os.environ.get("REPOSITORY") != "daijro/camoufox"' in gate
    assert "REPOSITORY: ${{ github.repository }}" in gate


# --- build.yml ---------------------------------------------------------------


def test_build_runs_only_when_dispatched():
    """A fork release is made by hand from dispatched runs, and publishing it
    creates its tag. A tag trigger then rebuilt all seven targets and, on
    success, attached them to the already-published release: runs 36006238588
    and 38362834381 (#203)."""
    workflow = yaml.safe_load(BUILD.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as the boolean True.
    assert set(workflow[True]) == {"workflow_dispatch"}
    assert "release" not in workflow["jobs"]
