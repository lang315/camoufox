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
    whose default is this fork's lang315/camoufox alone, and the fork publishes
    no Linux package: on the Linux runner the fetch tier would find no browser
    to grade a driver-only pull request against, and upstream's browser, which
    carries none of the fork's patches, would be a green about the wrong
    binary. Every run outside daijro/camoufox must take the build path, and
    must decide that before the changed-files classification can send it to
    fetch."""
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


# --- the gate's table ----------------------------------------------------------

GATE_TIERS = (
    "resolve static pythonlib typescript install build fetch-browser playwright "
    "patch-guards build-tester native typescript-browser growth e2e sundial summary"
).split()


def _run_gate(results: dict, *, built="true", has_sundial="false", repository="lang315/camoufox"):
    """Run the gate job's own script with a synthetic `needs` and return the
    process and the mark printed for each tier."""
    import json
    import os
    import subprocess
    import sys
    import textwrap

    gate = _job_block(WORKFLOW.read_text(encoding="utf-8"), "gate")
    script = gate.split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    needs = {name: {"result": results.get(name, "success")} for name in GATE_TIERS}
    env = {
        **os.environ,
        "RESULTS": json.dumps(needs),
        "BROWSER_CHANGED": built,
        "HAS_SUNDIAL": has_sundial,
        "REPOSITORY": repository,
    }
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], env=env, capture_output=True, text=True
    )
    table = proc.stdout.split("tier results:", 1)[1].split("\n\n", 1)[0]
    marks = {line.split()[1]: line.split()[0] for line in table.strip().splitlines()}
    return proc, marks


def test_the_gate_marks_an_excused_skip_as_a_skip_not_a_failure():
    """On a fork the fetch, install and sundial tiers are skipped by design, and
    the gate still printed FAIL beside them above "this pull request is
    mergeable" (runs 39793265227 and 39801913772, #273)."""
    proc, marks = _run_gate(
        {"fetch-browser": "skipped", "install": "skipped", "sundial": "skipped"}
    )
    assert proc.returncode == 0, proc.stdout
    assert {marks[t] for t in ("fetch-browser", "install", "sundial")} == {"skip"}
    assert "FAIL" not in marks.values()
    assert marks["pythonlib"] == "ok"


def test_the_gate_fails_a_skip_that_nothing_excuses():
    proc, marks = _run_gate({"playwright": "skipped"})
    assert proc.returncode == 1
    assert marks["playwright"] == "FAIL"
    assert "not mergeable:\n  - playwright: skipped" in proc.stdout


def test_the_gate_fails_a_tier_that_failed():
    proc, marks = _run_gate({"pythonlib": "failure"})
    assert proc.returncode == 1
    assert marks["pythonlib"] == "FAIL"
    assert "not mergeable:\n  - pythonlib: failure" in proc.stdout


def test_the_gate_does_not_excuse_a_skip_the_run_did_not_earn():
    """fetch-browser may skip only when the browser was built."""
    proc, marks = _run_gate({"fetch-browser": "skipped"}, built="false")
    assert proc.returncode == 1
    assert marks["fetch-browser"] == "FAIL"


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


def test_every_build_target_is_one_multibuild_builds():
    # A pair multibuild.py skips uploads nothing, so its leg fails and the run
    # reports failure (#200: linux i686 in the 'full' matrix).
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("multibuild", REPO_ROOT / "browser" / "multibuild.py")
    multibuild = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(multibuild)
    text = BUILD.read_text(encoding="utf-8")
    full = json.loads(text.split("echo 'json=", 1)[1].split("'", 1)[0])["include"]
    options = yaml.safe_load(text)[True]["workflow_dispatch"]["inputs"]["build_target"]["options"]
    pairs = {(leg["target"], leg["arch"]) for leg in full}
    pairs |= {tuple(o.split("-", 1)) for o in options if o != "full"}
    assert not pairs & set(multibuild.UNSUPPORTED), sorted(pairs & set(multibuild.UNSUPPORTED))


def test_every_job_declares_its_token_permissions():
    # AGENTS.md: least privilege, per job. A job with no `permissions:` at either
    # level runs with the repository's default token scope (#187).
    bare = []
    for path in sorted(WORKFLOW.parent.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "permissions" in workflow:
            continue
        bare += [f"{path.name}:{name}" for name, job in workflow["jobs"].items()
                 if "permissions" not in job and "uses" not in job]
    assert not bare, bare
