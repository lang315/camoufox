"""Fork-only checks on .github/workflows/tests.yml.

Kept out of test_ci.py on purpose: that file is upstream's (daijro/camoufox),
and a fork-only assertion there would conflict with every future sync that
touches it.
"""

from ci._util import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
GUARD = '"${{ github.repository }}" != "daijro/camoufox"'


def _scope_commands() -> str:
    """The shell of the `Does this change the browser?` step, comments dropped."""
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text.split("- name: Does this change the browser?", 1)[1].split("- name:", 1)[0]
    return "\n".join(
        line for line in step.splitlines() if not line.strip().startswith("#")
    )


def test_a_fork_never_grades_against_the_released_browser():
    """`camoufox fetch` resolves releases from pythonlib/camoufox/repos.yml,
    whose first entry is daijro/camoufox. On this fork the fetch tier would
    grade a driver-only pull request against upstream's browser, which carries
    none of the fork's patches -- a green about the wrong binary. Every run
    outside daijro/camoufox must take the build path, and must decide that
    before the changed-files classification can send it to fetch."""
    commands = _scope_commands()
    assert GUARD in commands, "the scope step has no fork guard"
    guard_at = commands.index(GUARD)
    assert guard_at < commands.index("git diff --name-only"), (
        "the fork guard runs after the changed-files check, which can already "
        "have chosen the fetch path"
    )
    assert "browser_changed=true" in commands[guard_at : guard_at + 300], (
        "the fork guard does not set browser_changed=true"
    )
