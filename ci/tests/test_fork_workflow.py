"""Fork-only checks on .github/workflows/tests.yml.

Kept out of test_ci.py on purpose: that file is upstream's (daijro/camoufox),
and a fork-only assertion there would conflict with every future sync that
touches it.
"""

import pytest

from ci._util import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
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
    """`camoufox fetch` resolves releases from pythonlib/camoufox/repos.yml,
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
