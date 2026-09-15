# Sync fork `main` with upstream daijro/camoufox (PR #772, the repo-wide test pipeline) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the single upstream commit `52d6746` (PR #772, "ci: a repo-wide test pipeline, and the one check that gates merge on it") into fork `main` through a `sync/upstream-772` branch in a fresh worktree, with every conflict resolved on a stated reason, every adopted CI decision either accepted deliberately or amended with fork evidence, and a post-merge build proving the browser the merge produces.

**Assumption (stated, not verified with the user):** "sync fork" means *upstream → fork `main`*, the same reading as the two prior syncs (`2026-09-07-sync-upstream-beta31.md`, `2026-07-18-sync-upstream-daijro.md`).

**Architecture:** Real `git merge --no-ff upstream/main`. `gh repo sync` stays forbidden: fork `main` is 466 commits ahead and a sync would force-push over all of it. Shape follows the prior two syncs: tracking issue → worktree → merge → per-file resolution table → local gates → `make dir` as the patch-stack gate → CI build → both test suites → PR with evidence.

## Measured state (2026-09-15)

```
main            27d5f7d   upstream.sh release=beta.31   pythonlib 0.5.6
upstream/main   52d6746   upstream.sh release=beta.31   pythonlib 0.5.6
merge-base      571e416a
main...upstream/main : 466 fork-only / 1 upstream-only
upstream.sh: byte-identical on both sides — this sync moves no browser version.
```

`52d6746` is one commit but 268 files: it adds `ci/` (the pipeline), `native-tests/`, `.github/workflows/tests.yml` and `.github/actions/prepare-browser/`, deletes the vendored ~v1.55-era Playwright fork under `tests/` (207 files) leaving only `tests/patches/` and `tests/camoufox/`, deletes `.github/workflows/lint.yml` (folded into the pipeline's static tier), and rewrites the `Makefile`'s `tests` target onto `ci.run_playwright`.

Trial merge already performed in a scratch worktree: **8 content conflicts, 175 conflicted lines, no modify/delete conflicts.** Fork references to the deleted `tests/` harness are comments only (`additions/juggler/content/FrameTree.js:570`, `pythonlib/tests/test_virtdisplay_render.py:56`) — no live code path breaks.

### Two browser-layer changes come with this merge

Both auto-merge, and both mean the merged tree is **a different browser** than `27d5f7d`:

- `additions/juggler/TargetRegistry.js` — screencast `deviceWidth`/`deviceHeight` now report the viewport the frame depicts rather than the JPEG's own scaled dimensions.
- `additions/juggler/content/FrameTree.js` — `Cu.nukeSandbox()` on frame destruction. The master sandbox is built over `sandboxPrototype: domWindow` with a system principal, so a destroyed iframe (what an ad stack produces continuously) previously kept the whole document alive.

Consequence for scheduling: the three builds dispatched today on `27d5f7d` (`34936833501` windows-x86_64, `34936841599` macos-x86_64, `34936850063` macos-arm64) are a valid release of `27d5f7d` and must not be cancelled, but they do **not** cover the merged tree. A fresh dispatch is required after the merge, and `build.yml` on the fork is dispatch-only, so nothing will do it automatically.

## Conflict resolution table (measured in the trial merge, all eight verified to compile and pass)

| File | Fork side | Upstream side | Resolution and reason |
|---|---|---|---|
| `.gitignore` | `/local/`, goapi binaries, `.rehearse/`, `*.rej` | `.harness-work/`, `.ci-work/` | **Union.** Disjoint entries; `.ci-work/` is now a real output directory. |
| `CLAUDE.md` | build-tester headful/xvfb rule (#75), `make tests` description | the new pipeline's tester inventory | **Union**, then edit so `make tests` describes `ci.run_playwright`, which is what the merged `Makefile` runs. |
| `CONTRIBUTING.md` | headful/#75 paragraph | `ci.run_build_tester` entry point | **Union.** |
| `build-tester/requirements.txt` | `cloverlabs-camoufox`, `playwright==1.55.0`, `marionette_driver` | `-e ../pythonlib`, `playwright<1.63` | **Upstream, plus the fork's `marionette_driver`.** Two independent reasons below. |
| `build-tester/scripts/run_tests.py` | `--json` → `args.json` | `--json` → `args.json_out` | **Upstream** (rename only). |
| `build-tester/scripts/runner.py` | `json_path=` | `json_out=` | **Upstream** (same rename). |
| `pythonlib/camoufox/utils.py` | `_bundle_verstr(exe) or installed_verstr()` (#97) | `resolve_verstr(exe)` | **Fork.** Convergent evolution — both read `application.ini` beside the binary — but the fork's also handles the macOS bundle layout (binary in `Contents/MacOS`, `application.ini` in `Contents/Resources`), which upstream's `parent/application.ini` misses. Keep `_bundle_verstr` and delete upstream's now-orphaned `resolve_verstr` (merged tree `utils.py:865`, no remaining callers — its only one was the conflicted line). If it is kept as a public name instead, make it a wrapper and note the shape difference: `_bundle_verstr` returns the major only, upstream's the full string; today's single caller `.split('.', 1)[0]`s either. |
| `pythonlib/tests/test_launch_geometry.py` | `INSTALL_DIR` tempdir, `repo_get_path` (#108), `add_default_addons` (#110) | `has_display` stub (headless runner) | **Union of stubs.** Both guard real failures; neither subsumes the other. |

### Why `cloverlabs-camoufox` must go

`ci/tribal-rules.yml` carries `no-third-party-camoufox-distribution` as a settled decision, and the static tier enforces it. Keeping the fork side fails the merge's own gate. Independently, the fork's `build-tester/run_tests.sh` already does `pip uninstall -y cloverlabs-camoufox` and installs `-e ../pythonlib`, so the fork converged on upstream's answer months ago and only the requirements file lagged.

### Why the `playwright==1.55.0` pin is now unsupported — and what to do instead

The pin was added `74c6158` (2026-08-23) with the reason "this juggler's protocol schema rejects `viewport.isMobile`". Upstream's `2b662a8` "Support Playwright 1.61+" landed 2026-08-28, five days later, and is **already in fork `main`** (`additions/juggler/protocol/Protocol.js:81,815` accept `isMobile`; `pythonlib/pyproject.toml` already caps `playwright = "<1.63"`). `memory/build-tester-playwright-pin.md` names the binary its 0/0 Grade F was measured on — `camoufox-152.0.4-beta.25` — which predates `2b662a8` by more than a month, so the measurement is sound and simply describes a browser the fork no longer builds. (Not to be confused with the fork's one published release, `150.0.2-beta.25`: different version line, same beta number.) The pin commit itself names no binary.

Note the pin exists in **two** places with different values after the merge: `build-tester/requirements.txt` (upstream's `<1.63`, used by `ci.run_build_tester` in CI) and `build-tester/run_tests.sh:66` (the fork's hardcoded `'playwright==1.55.0'`, used by every local run). Two entry points answering differently is the harness-drift failure the pin was meant to prevent. Unify them on one measured answer.

The measurement does not need the post-merge binary: `2b662a8` is in `27d5f7d`, so today's completed builds are a valid testbed.

## Static tier: already run against the resolved merge

Environment: macOS host, Python 3.12.1, venv from `ci/requirements.txt` + `pytest` + `-e pythonlib`, in the scratch worktree with all eight conflicts resolved as tabled above.

| Check | Result |
|---|---|
| `python3 scripts/check-input-dispatch.py` | ok — 16 files scanned, all synthesized input through `MouseDispatch.js` |
| `python3 -m pytest ci/tests -q` | 167 passed |
| skiplist validation | OK — 10 entries, every one with a reason |
| `python3 -m ci.run_native --subset rules` | 22 passed, **2 failed** |
| `pythonlib` suite (`pytest tests -q`) | 311 passed, 9 skipped |

The two rule failures were separated with a control: the same subset run on a pristine `upstream/main` worktree on the same host.

- `displayfd-not-lockfile-scan` — **fails on pristine upstream too.** Host artifact: no Xvfb on macOS, so the captured argv is empty. Not a fork finding; re-check on Linux rather than acting on it.
- `composite-extension-off` — **passes on pristine upstream, fails on the merged tree.** A real divergence, and the one open decision in this sync.

### The Composite decision (the only substantive disagreement)

Upstream's rule says the X Composite extension stays **off**: #93 was a Juggler bug fixed by capturing the screencast from the compositor rather than libwebrtc's X11 window capturer, and with that capturer gone, enabling Composite is neither dangerous nor useful. Their measurement: composite off → a valid 24-frame `.webm`; composite on → SIGSEGV in the X11 capturer.

At the merge base the default was off. The fork flipped it to **on** in `efb0a09` (2026-08-25, "re-enable Composite by default -- it is still required for video"), replacing upstream's table with its own: on a beta.29 Linux build, `headless="virtual"` with Composite off produced a 110-byte empty container while Composite on produced a 54 KB working video, with `headless=True` (no Xvfb, 60 KB) as the control showing `record_video` itself works. Upstream then codified the off state as a rule in #772 (2026-09-14).

`virtdisplay.py` auto-merges cleanly and the result is coherent, not a hybrid: the two sides changed different regions — the fork the composite comment and default, upstream the teardown path (cleanup no longer gated on having done the killing, so a crashed Xvfb's socket is still removed). The merged file therefore carries the fork's Composite-on default and upstream's teardown fix, which is why only the rule, and not the code, is red.

The two tables contradict each other, upstream's own text says its numbers were taken "before that fix", and the fork's are three weeks newer. `HeadlessWindowCapturer.cpp` has been in the tree since the 2024 initial release, so its presence dates neither measurement. Do not resolve this by preference:

- [ ] Re-measure on the post-merge **Linux** build, reproducing the fork's three-row table (headless baseline, virtual+off, virtual+on) with byte sizes.
- [ ] If Composite is still required for video, keep the fork default and amend `ci/tribal-rules.yml` + `native-tests/test_tribal_rules.py:130` with the new table and a link to this run — the rule's `expect:` block only checks `COMPOSITE_ENV_VAR`'s name, so the `-extension` assertion in the test is the part that must change.
- [ ] If Composite is no longer required, revert `efb0a09` and record the retraction where its table currently sits.
- [ ] Either way, state which binary each table came from. Neither existing table does.

## CI adoption decisions (the merge brings a pipeline; the fork has to choose how much of it to run)

- [ ] **`repos.yml` grades against the wrong binary.** `tests.yml:554-581` runs `python -m camoufox fetch` whenever `browser_changed == 'false'` — which the scope step (`:150-169`) decides by testing the PR's changed files against `^(patches/|additions/|settings/|assets/|upstream\.sh|Makefile|scripts/)` — and `camoufox fetch` resolves releases through `pkgman.py` from `pythonlib/camoufox/repos.yml`, whose first entry is `daijro/camoufox, camoufox/camoufox`. On the fork that means a driver-only PR is graded against **upstream's** browser, which carries none of the fork's font work (#84, #93, #96, #105, #108). This is a green about the wrong binary — the exact shape of CLAUDE.md lesson 9, baked into CI. The fork publishes one prerelease (`macwin-test-150.0.2-beta.25`, 2026-07-01), so pointing the fetch at fork releases is not currently viable; pick one of: force the build tier on the fork, gate the fetch tier behind a fork-release check, or narrow `tests.yml`'s triggers until fork releases exist.
- [ ] **Triggers and cost.** `tests.yml` runs on every `pull_request`, every push to `main`, and a twice-weekly `cron` that exists to keep the ccache warm. Decide deliberately whether the fork wants all three; a browser-touching PR is ~70 minutes of build before the suites start.
- [ ] **Workflow overlap.** The merge deletes `lint.yml` (its content moves into the static tier) — confirm branch protection does not require `lint` by name. `pythonlib.yml` and the pipeline's `pythonlib` tier now cover the same ground on the same PRs; `goapi.yml` and `smoke.yml` stay fork-only and untouched.
- [ ] **Secrets.** `SUNDIAL_*` gate a job that ships disabled (`ci/sundial.yml: enabled: false`), and `CAMOUFOX_PASSWD` has no consumer anywhere in the tree. Absent secrets should be harmless; confirm on the first run rather than assuming.
- [ ] **Patch guards are glob-driven** (`tests/patches/*.py`), not a hardcoded map, so the fork's extra guards are picked up automatically. Policy is zero failures.

## Tasks

1. **Tracking issue** — open one describing the sync; every PR must close an issue (CONTRIBUTING).
   *Verify:* issue number exists and is referenced by the branch's first commit.
2. **Branch and worktree** — `sync/upstream-772` off `main` in a fresh worktree. The trial worktree at `scratchpad/mergetest` holds the resolved merge and can seed the resolutions; remove both it and `scratchpad/upstreamctl` (`git worktree remove`) when done.
   *Verify:* `git worktree list` shows the new tree; `git log -1` on it is `27d5f7d`.
3. **Merge and resolve** — `git merge --no-ff upstream/main`, apply the eight resolutions from the table.
   *Verify:* `git diff --name-only --diff-filter=U` is empty; `python3 -c "import ast; ..."` parses both edited Python files.
4. **Composite decision** — the four checkboxes above. Blocks the PR only if the re-measurement contradicts whichever default the branch ships.
   *Verify:* a three-row byte-size table in the PR body naming the build it came from.
5. **Unify the Playwright pin** — one value in `build-tester/requirements.txt` and `build-tester/run_tests.sh`, chosen by measurement against build `34936833501` / `34936841599` / `34936850063` (all on `27d5f7d`, which already contains `2b662a8`).
   *Verify:* `run_tests.sh` against a completed build scores ≈1050/1064 Grade A on the chosen version. Then update `memory/build-tester-playwright-pin.md` with the run id, or retire it.
6. **CI adoption** — the five checkboxes above, each recorded in the PR body with its reason.
   *Verify:* `.github/workflows/` contents match the decisions; branch protection's required check list is consistent with whatever gates merges.
7. **Local gates on the merged tree** — static tier (all four checks), `pythonlib` pytest, `goapi` `go test ./...`, then `make dir` as the patch-stack gate.
   *Verify:* static tier green apart from any failure reproduced on a pristine `upstream/main` control; `make dir` reaches `_READY` with no `.rej`.
8. **Build and browser suites** — dispatch `build.yml` for `linux-x86_64` first (cheapest, and the only host the guards can measure), then `windows-x86_64`, `macos-x86_64`, `macos-arm64`. Run `build-tester` headful, `service-tester`, and `smoke.yml` against the linux artifact.
   *Verify:* run ids resolved to their builds, and each build resolved to this branch, before any number from them is quoted (lesson 9).
9. **PR** — evidence in the body: command output with exit status for every gate, the composite table, the pin measurement, and an explicit "NOT verified" section for anything skipped (the macOS host is unmeasured by the Linux guards, as always).

## Global constraints

- `gh repo sync` is forbidden (466 fork-only commits).
- Every `gh` invocation needs `--repo lang315/camoufox`; the `upstream` remote otherwise wins and dispatches fail with `HTTP 403: Must have admin rights`.
- Hand-written patch hunks need balanced leading/trailing context; dry-run with `patch -p1 --forward -l --binary --dry-run < patches/x.patch`. `git apply --check` is not a valid pre-flight.
- No edits inside `camoufox-*/`; persist as patches.
- Do not cancel the three in-flight `27d5f7d` builds; they are a valid release of that commit and a valid testbed for task 5.

## What this plan does not cover

The merge changes the browser (two Juggler changes), so every fork claim measured on a pre-merge binary is, strictly, about a different browser. The font findings are unaffected in mechanism — neither Juggler change touches font lookup — but no re-measurement of the font arms is scheduled here, and the smoke guard remains Linux-only, so macOS and Windows stay unmeasured exactly as they were before this sync.
