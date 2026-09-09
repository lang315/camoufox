# Fonts round 2 (#80, #82, #83, #87, #88; admin #81, #89) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close #80 (`url()` web fonts refused when a fonts list is configured), #82 (the U+FFFD replacement-character fallback cache leaks a resolved face across contexts) and #83 (the per-context list is not enforced in the process that renders), measure #87 (native Windows) and #88 (the unidentified 375.7 face), and finish the admin left on #81 and #89 — on one branch, `fix/fonts-round2`, in one PR marked "part of #44".

**Architecture:** Three phases with a measurement gate between them. Phase B edits `.github/workflows/smoke.yml` only and runs against an existing build artifact, adding a discriminator arm for #83 (`b2r`), repairing arms (j)/(j2) so they can go red for the bug they guard, adding a #80 render arm (k) with a purpose-built font, and adding a #88 width-match arm (h'). The arm (b2r) reading decides whether Phase C carries the #83 fix or a `MOZ_LOG` discriminator instead. Phase C makes the C++ changes as patch edits through the workspace flow — `patches/font-hijacker.patch` for #80, `patches/font-list-spoofing.patch` for #82/#81 and (conditionally) #83 — then dispatches three builds at one sha. Phase D verifies on those binaries, Phase E runs the Windows probe by hand, Phase F opens and merges the PR.

**Tech Stack:** GNU patch (`/opt/homebrew/bin/gpatch`), `make dir` / `make revert` over the Firefox 152.0.4 tree under `camoufox-152.0.4-beta.31/`, `.superpowers/sdd-44/apply_upto.py` for the workspace flow, GitHub Actions (`build.yml` and `smoke.yml`, both `workflow_dispatch`), Playwright 1.55.0, fontTools, uv-managed Python venvs, `gh`.

**Design spec:** `docs/superpowers/specs/2026-09-09-fonts-round2-design.md` (commit `35e3e93`).
**Recon (untracked scratch):** `.superpowers/sdd-fonts2/code-recon.md`.

## Global Constraints

Copied verbatim from the spec's "Global constraints" section; every task inherits them.

- Patches are edited through the workspace flow, never by hand: `make revert`, apply the
  stack up to the target patch (`.superpowers/sdd-44/apply_upto.py <patch>` reproduces
  `scripts/patch.py`'s order and sets `first-checkpoint`), edit the tree, then regenerate
  with `git add -A && git diff --cached first-checkpoint` inside the source dir (the patch
  creates new files, so `git diff` alone misses them). Hand-written hunks must have
  balanced leading/trailing context; dry-run with
  `patch -p1 --forward -l --binary --dry-run` (GNU patch; `gpatch` on macOS), never
  `git apply --check`. `0 FAILED` is not a placement proof: read the tree after applying.
- Never `git add -A` in the repo root. Never commit `_READY`, `camoufox-*/`, `.venv`,
  `.superpowers/`, `firefox-*.tar.xz`, `service-tester/proxies.txt`. Never print or quote
  `service-tester/proxies.txt` or any log line containing the proxy host.
- No force-push on shared branches. Commits end with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Every number, sha, run id and file line that goes into a commit message, an issue, or
  the PR body is read back from the actual state first (CLAUDE.md lesson 6).
- Smoke verdicts obey CLAUDE.md lesson 4: a reference is a control only if it is
  guaranteed to differ from the value under test. Every new or repaired arm states, in a
  comment above it, what would produce its GREEN wrongly and how the arm rules that out.
- `CamouIsFontAllowed` keeps failing open on context 0 (CLAUDE.md lesson 5). Changing
  that default is a non-goal here and is stated as NOT-verified in the PR.
- Both test suites run against the final binary: `build-tester` headful
  (`DISPLAY=:0`, playwright pinned 1.55.0, `checks-bundle.js` rebuilt from source) and
  `service-tester` with `service-tester/proxies.txt` supplied by the user.

Operational constraints that follow from this repo, added by this plan:

- Repo root is `/Users/lang/GolandProjects/github.com/lang315/camoufox`; the source tree is
  `camoufox-152.0.4-beta.31/`. Branch `fix/fonts-round2`, checked out at the repo root, no
  worktree, one implementer at a time. All paths in commands are absolute or relative to the
  repo root unless a step says otherwise.
- `/usr/bin/patch` on macOS is Apple patch 2.0 and must not be used. Use
  `/opt/homebrew/bin/gpatch`, and pass it to the build as `CAMOU_PATCH=/opt/homebrew/bin/gpatch`.
- `scripts/patch.py` deletes `.rej` files, so the count of `FAILED` lines in the `make dir`
  log is the signal. Grep the same log for `fuzz` and `offset`: `0 FAILED` with fuzz means
  hunks were placed somewhere other than where they were written.
- CI: `gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round2 -f build_target=<target>`
  (40–95 min). `gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round2 -f run_id=<build run id>`
  (~15 min). Read a run with `gh run view <id> --json status,conclusion` and
  `gh run view <id> --log`. In the `#44` step's log, runtime lines are the ones that do
  **not** contain the ANSI marker `36;1m` (those are the workflow echoing its own source).
  Download artifacts with `gh api repos/lang315/camoufox/actions/artifacts/<id>/zip > <file>.zip`;
  `gh run download` has stalled before.
- Evidence and scratch live in `.superpowers/sdd-fonts2/` (ignored via `.git/info/exclude`).
  Nothing else keeps it. `.superpowers/sdd-fonts2/progress.md` is the ledger; append one
  line per completed step.
- Baselines to compare against, read back before they are quoted: `build-tester` on `main`
  beta.31 macOS arm64 = Grade A 1061/1070 with 8× `canvasPerturbation` marker and 1×
  `noSwiftShader` as the known fails; `service-tester` on the PR #84 macOS candidate with a
  live proxy = Grade A 384/384.

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `.github/workflows/smoke.yml` | 2, 7 | Every measurement. New arms (b2r), (k), (h'); repaired (j)/(j2); hoisted process instrumentation; `EXPECTED_RED`. |
| `.superpowers/sdd-fonts2/check_smoke_python.py` | 2 | New, untracked. Extracts each `python - <<'MARKER'` heredoc from a workflow and byte-compiles it, so a syntax error costs a second instead of a CI run. |
| `patches/font-hijacker.patch` | 3 | #80. Adds `FontFaceImpl::CamouHasNonLocalSource()` and consults it at the three family-name refusal sites. |
| `patches/font-list-spoofing.patch` | 4, 5 | #82/#81 read-path gating in `gfxPlatformFontList.cpp` and `gfxTextRun.cpp`; conditionally the #83 cross-process list in `dom/base/FontListManager.{h,cpp}`. |
| `build-tester/scripts/probe_windows_fonts.py` | 8 | New, tracked. Standalone Playwright probe for #87, run by hand on the Windows build PC. |
| `.superpowers/sdd-fonts2/*.md`, `*.log`, `*.zip` | all | Untracked evidence: `progress.md`, `gate.md`, smoke logs, build-tester/service-tester output, issue bodies, PR body. |

Not touched by any task: `Makefile`, `upstream.sh`, `additions/`, `settings/`, `pythonlib/`,
every other file under `patches/`.

---

### Task 1: Phase A — issue admin (#81 comment, close #89, two new issues)

No build, no patch, no code. Four `gh` calls and four read-backs.

**Files:**
- Create: `.superpowers/sdd-fonts2/issue-81-comment.md` (untracked)
- Create: `.superpowers/sdd-fonts2/issue-89-close.md` (untracked)
- Create: `.superpowers/sdd-fonts2/issue-new-speechvoices.md` (untracked)
- Create: `.superpowers/sdd-fonts2/issue-new-fontface-status.md` (untracked)
- Modify: `.superpowers/sdd-fonts2/progress.md` (untracked)

**Interfaces:**
- Consumes: nothing.
- Produces: two new issue numbers, written into `.superpowers/sdd-fonts2/progress.md` as
  `SPEECHVOICES_ISSUE=<n>` and `FONTFACE_STATUS_ISSUE=<n>`. Task 9's PR body cites both,
  and Task 3's commit message cites `FONTFACE_STATUS_ISSUE`.

- [ ] **Step 1: Write the #81 comment body**

Create `.superpowers/sdd-fonts2/issue-81-comment.md` with exactly this text:

```markdown
The clear-on-install fix covers the sequence it was measured on, not the ordinary one.

`FontListManager::SetFontList` calls `gfxPlatformFontList::ClearCodepointsWithNoFonts()` (`dom/base/FontListManager.cpp:47-55`) when a context **installs** its list. The leak this issue describes fires when a context **reads**. Those are different moments, and the ordinary shape of a caller that sets up its contexts before navigating puts both installs before either read:

1. Context A calls `setFontList`; the clear runs.
2. Context B calls `setFontList`; the clear runs again.
3. A renders. Its own correctly gated fallback finds nothing for some codepoint, and the miss is written to the process-wide `mCodepointsWithNoFonts` at `gfx/thebes/gfxPlatformFontList.cpp:1403`.
4. B renders. `gfxFontGroup::FindFontForChar` consults `SkipFontFallbackForChar()` at `gfx/thebes/gfxTextRun.cpp:3494`, hits A's miss, and returns early. B's own gate never runs, and B renders tofu for a codepoint its own list covers.

Nothing clears `mCodepointsWithNoFonts` between steps 3 and 4. The audit backing this comment found no other reset in the tree: the only writes are the seed in `InitializeCodepointsWithNoFonts()` (`gfxPlatformFontList.cpp:867-875`), the miss at `:1403`, and `ClearCodepointsWithNoFonts()` itself (`gfxPlatformFontList.h:689-694`). In particular nothing clears it when an async cmap load completes.

The verified control-RED / treatment-GREEN result on smoke arm (i) stands for the sequence it tested, which is install, render, install, render. It does not generalise to install, install, render, render.

The fix belongs on the read path, not the install path. A context that has its own list must not honour a process-wide negative-cache hit, and must not record its own misses into it. That change is being made under #82, which touches the same function for the U+FFFD positive cache. This issue stays open until it lands and both arm (i) and a new ordering arm are green on the same run.

The existing clear-on-install is kept. It is harmless, and it covers the case where a context installs its list after an earlier context has already missed.
```

- [ ] **Step 2: Post it and read it back**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
gh issue comment 81 -R lang315/camoufox --body-file .superpowers/sdd-fonts2/issue-81-comment.md
gh issue view 81 -R lang315/camoufox --json state,comments \
  --jq '.state + " | last comment starts: " + (.comments[-1].body[0:60])'
```
Expected: `OPEN | last comment starts: The clear-on-install fix covers the sequence it was measu`.
If `state` is not `OPEN`, stop and report: the spec requires #81 to stay open until the #82 fix lands.

- [ ] **Step 3: Write the #89 close comment and close it**

Create `.superpowers/sdd-fonts2/issue-89-close.md`:

```markdown
Fixed and verified.

The harness fix `8f8503e` is in `main` (it arrived with PR #84, merged as `f1b60a6`). The final `service-tester` run on the PR #84 macOS arm64 candidate with a live proxy scored Grade A 384/384 across three profiles with every section passing, on the same binary and the same proxy that scored 0/0 before the fix.

The second half of the report is not closed by this, and is restated here so it is not lost: every earlier claim citing a `service-tester` score against a camoufox-152 binary was produced before the DOM hand-off was in place, so it measured nothing and remains unsupported. That includes PR #86's own `service-tester` line, which already disclosed itself as not verified.

The suggested guard against a silent `0/0` was not implemented and is not tracked by this issue. Open a separate one if it is wanted.
```

```bash
gh issue close 89 -R lang315/camoufox --comment "$(cat .superpowers/sdd-fonts2/issue-89-close.md)"
gh issue view 89 -R lang315/camoufox --json state,stateReason --jq '.state + " " + (.stateReason // "-")'
```
Expected: `CLOSED COMPLETED`.

- [ ] **Step 4: File the SpeechVoicesManager measurement issue**

Create `.superpowers/sdd-fonts2/issue-new-speechvoices.md`:

```markdown
`SpeechVoicesManager` has the same storage asymmetry that is the leading hypothesis for #83, and nothing has measured whether it produces the same defect.

## The asymmetry

The per-context *value* lives in a process-local static:

```cpp
// dom/base/SpeechVoicesManager.cpp:12-13
static mozilla::Mutex sVoicesMutex("SpeechVoicesManager");
static nsTHashMap<nsUint32HashKey, nsTHashSet<nsString>> sVoicesMap;
```

while the one-shot *disable flag* that hides the WebIDL setter after the first call goes through `RoverfoxStorageManager`, which is explicitly cross-process: `dom/base/RoverfoxStorageManager.h:12-15` describes it as "Cross-process key-value storage using Firefox Preferences + local cache", and `RoverfoxStorageManager.cpp:50-55` shows a content process sending `SendRoverfoxStoragePut` so the parent can set a default-branch pref that every content process reads.

For comparison, the four managers in the same directory:

| Manager | Where the per-context value lives | Cross-process |
|---|---|---|
| `WebGLParamsManager` | `RoverfoxStorageManager::PutString` (`WebGLParamsManager.cpp:26,38`) | yes |
| `AudioFingerprintManager` | `RoverfoxStorageManager::PutUint` (`AudioFingerprintManager.cpp:31`) | yes |
| `SpeechVoicesManager` | `static nsTHashMap` (`SpeechVoicesManager.cpp:12-13`) | **no** |
| `FontListManager` | `static nsTHashMap` (`FontListManager.cpp:14`) | **no** |

## Why it may matter

If a context's `about:blank` and its real document land in different content processes, the first process stores the value and sets the cross-process flag; the second process finds the setter already disabled, never receives the value, and answers from the unspoofed default. That is the mechanism under test for #83, and `FontListManager` is the other entry in the "no" column.

## The ask is measurement, not a fix

Two contexts in one launch, each setting a different voice list through the init script, each reading `speechSynthesis.getVoices()` after a navigation, with the content-process ids sampled between `new_page()` and `goto()` — the same instrumentation #83 uses. If the second context reads the host's real voices, this is the same bug and should be fixed the same way.

Related: #83.
```

```bash
gh issue create -R lang315/camoufox \
  --title "SpeechVoicesManager stores its per-context value process-locally while its disable flag is cross-process (#83's shape) — measure" \
  --body-file .superpowers/sdd-fonts2/issue-new-speechvoices.md
```
The command prints the new issue URL. Read it back and record the number:
```bash
gh issue view <n> -R lang315/camoufox --json number,title,state --jq '"\(.number) \(.state) \(.title)"'
echo "SPEECHVOICES_ISSUE=<n>" >> .superpowers/sdd-fonts2/progress.md
```
Expected: `<n> OPEN SpeechVoicesManager stores its per-context value process-locally ...`.

- [ ] **Step 5: File the `FontFaceImpl::SetStatus` real-status issue**

Create `.superpowers/sdd-fonts2/issue-new-fontface-status.md`:

```markdown
`font-hijacker.patch` replaced the whole upstream body of `FontFaceImpl::SetStatus`. The parameter `aStatus` is now unused on every call:

```cpp
// layout/style/FontFaceImpl.cpp:354
void FontFaceImpl::SetStatus(FontFaceLoadStatus aStatus) {
  gfxFontUtils::AssertSafeThreadOrServoFontMetricsLocked();
  nsAutoCString fontFamily;
  if (nsAtom* familyName = GetFamilyName()) {
    fontFamily = nsAtomCString(familyName);
  }
  if (IsFontAllowed(fontFamily)) {
    mStatus = FontFaceLoadStatus::Loaded;
  } else {
    mStatus = FontFaceLoadStatus::Error;
  }
  ...
```

The lines the patch removed are the `mStatus == aStatus` early-out, the whole `aStatus < mStatus` backwards-transition guard, and `mStatus = aStatus`. There is no branch on source type, load state or face kind, so the real network result carried by the calls from `FontFaceImpl::Entry::SetLoadState` (`FontFaceImpl.cpp:812` and `:816`) is discarded.

## Observable effect

A `url()` face on an allowed family name reports `loaded` even when the download genuinely failed — a 404, a CORS refusal, or malformed font bytes. `Loading` is unreachable as an observable state, because every `SetStatus` call collapses to `Loaded` or `Error`. A page can serve a deliberately broken font URL and read back a status no other browser would give it.

This is separate from the blocking defect in #80. The #80 fix lets a `url()` face skip the family-name gate; it does not touch `aStatus`, and after it lands this defect is still present.

## Why restoring it needs its own build and its own arm

Four couplings, all read from the tree:

1. `FontFace::Status()` (`layout/style/FontFace.cpp:263-286`) never reads `mStatus` — it recomputes from `IsFontAllowed`. Restoring `mStatus` alone changes nothing a page can observe. The getter would have to fall through to `mImpl->Status()` for non-local faces.
2. `SetStatus` ends by calling `UpdateOwnerPromise()`, and `UpdateOwnerPromiseSync` (`FontFaceImpl.cpp:407-425`) resolves or rejects `mLoaded` from `mStatus`. `FontFace::Load()` (`FontFace.cpp:288-318`) already resolves or rejects `mLoaded` synchronously from the allowlist. `MaybeResolve`/`MaybeReject` are first-wins, so the immediate answer wins and the real load result is dropped — the promise and `status` could then disagree.
3. `FontFaceImpl::Load()` has no caller anywhere in the tree; the fork's `FontFace::Load()` deleted it. So a `url()` face that is `load()`ed but never added to `document.fonts` gets no user font entry, no `SetLoadState`, and `mStatus` stays `Unloaded` forever, next to an already-resolved promise. Restoring real status therefore also requires restoring `mImpl->Load()` for non-local faces.
4. The deleted backwards-transition guard has to come back with it. A rule-backed face whose entry is replaced by `FontFaceSetDocumentImpl::InsertRuleFontFace` through the `mLocalRulesUsed` branch (`FontFaceSetDocumentImpl.cpp:541-557`) can be handed a lower status than it already has, and `SetUserFontEntry`'s own `newStatus > mStatus` check at `FontFaceImpl.cpp:597` covers only its own call.

## Ask

Restore real `FontFaceLoadStatus` for faces with a non-local source, together with items 1 to 4, and add a smoke arm that serves a deliberately failing `url()` on an allowed family and asserts `error`.

Related: #80, #44.
```

```bash
gh issue create -R lang315/camoufox \
  --title "FontFaceImpl::SetStatus discards aStatus, so a url() face whose download fails reports 'loaded'" \
  --body-file .superpowers/sdd-fonts2/issue-new-fontface-status.md
gh issue view <n> -R lang315/camoufox --json number,title,state --jq '"\(.number) \(.state) \(.title)"'
echo "FONTFACE_STATUS_ISSUE=<n>" >> .superpowers/sdd-fonts2/progress.md
```
Expected: `<n> OPEN FontFaceImpl::SetStatus discards aStatus ...`.

- [ ] **Step 6: Record and commit**

Nothing in this task is tracked by git — all four bodies live under `.superpowers/`. There
is no commit. Append one line to the ledger instead:

```bash
cat >> .superpowers/sdd-fonts2/progress.md <<'EOF'
Task 1 (Phase A admin): complete. #81 commented (read-back OPEN), #89 closed COMPLETED,
two issues filed (see SPEECHVOICES_ISSUE / FONTFACE_STATUS_ISSUE above). No git commit:
every artefact is under .superpowers/.
EOF
```

---

### Task 2: Phase B — six smoke arms, one dispatch, the #83 gate

Everything in this task is inside the `#44` step of `.github/workflows/smoke.yml` (the step
named `per-context font list beats the launch whitelist (#44 regression guard)`, which starts
at line 541). No patch, no build. The run uses the existing Linux build artifact from run
`34236331658` (head `8990915`; the delta from `main` `f1b60a6` to the branch tip is
documentation only, so the binary is the right one).

Line numbers below are against the branch tip `35e3e93`. Apply the edits **bottom-up** (the
highest line number first) so earlier edits do not shift later anchors, or anchor every edit
on the quoted text rather than the number.

**Files:**
- Modify: `.github/workflows/smoke.yml` (lines 712, 971, 1414, 1718, 1915, 2105, 2172, 2551, 2696, 2777)
- Create: `.superpowers/sdd-fonts2/check_smoke_python.py` (untracked)
- Create: `.superpowers/sdd-fonts2/gate.md` (untracked)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `.superpowers/sdd-fonts2/gate.md`, containing exactly one of the two lines
  `GATE: H1 CONFIRMED` or `GATE: H1 REFUTED`, plus the arm lines it was read from. Task 5
  branches on that line and nothing else. Also produces the leak signature and the repaired
  arms that Task 7 re-reads after the fix.
- Produces, for later tasks in this file: the helper `tab_pids()` (returns a `set` of pid
  strings, or a string beginning `ERR:`), and `two_contexts_one_launch(list_a, list_b, js,
  extra_prefs=None)` which now returns a **3-tuple** `(result_a, result_b, pids)` where
  `pids` is `{"after_a": <set>, "after_b": <set>}`.

- [ ] **Step 1: Write the embedded-Python syntax checker**

There is no such check in the repo today (verified: `grep -rn "py_compile\|yaml.safe_load"
.github/ scripts/` returns nothing). Without it a typo inside a heredoc is only discovered
15 minutes into a CI run. Create `.superpowers/sdd-fonts2/check_smoke_python.py`:

```python
#!/usr/bin/env python3
"""Extract every `python - <<'MARKER' ... MARKER` heredoc from a GitHub Actions
workflow and byte-compile it, so a syntax error costs a second instead of a run.

Usage: python3 check_smoke_python.py [workflow.yml] [outdir]
Exits non-zero if any block fails to compile.
"""
import os
import re
import sys
import textwrap
import py_compile

WF = sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/smoke.yml"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/smoke-py"

src = open(WF, encoding="utf-8").read().splitlines()
# The step bodies use both `python - <<'PY'` and
# `xvfb-run -a --server-args="..." python - <<'PY2'`, so match the tail.
start_re = re.compile(r"^\s*.*\bpython3?\s+-\s+<<'([A-Za-z0-9_]+)'\s*$")

blocks = []
i = 0
while i < len(src):
    m = start_re.match(src[i])
    if not m:
        i += 1
        continue
    marker = m.group(1)
    body = []
    j = i + 1
    while j < len(src) and src[j].strip() != marker:
        body.append(src[j])
        j += 1
    if j >= len(src):
        sys.exit(f"FATAL: heredoc {marker} opened at line {i + 1} was never closed")
    blocks.append((i + 1, marker, textwrap.dedent("\n".join(body)) + "\n"))
    i = j + 1

if not blocks:
    sys.exit(f"FATAL: no python heredocs found in {WF} -- the regex stopped matching")

os.makedirs(OUT, exist_ok=True)
bad = 0
for lineno, marker, body in blocks:
    path = os.path.join(OUT, f"block_{lineno}_{marker}.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    try:
        py_compile.compile(path, doraise=True)
        print(f"OK   line {lineno:>5} {marker:<4} {len(body.splitlines()):>4} lines")
    except py_compile.PyCompileError as e:
        bad += 1
        print(f"FAIL line {lineno:>5} {marker:<4}\n{e}")

print(f"{len(blocks)} block(s), {bad} failed")
sys.exit(1 if bad else 0)
```

Run it once **before** any edit, to establish the baseline:
```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml \
  "$TMPDIR/smoke-py-before"
```
Expected: a list of `OK` lines and a final `N block(s), 0 failed`. If it reports any failure
on the unmodified file, stop — the extractor is wrong, not the workflow.

- [ ] **Step 2: Hoist the process instrumentation above the arms that need it**

`import subprocess` and `content_pids()` are defined at lines 2551-2561, after arms (b2),
(i), (j) and (j2) — all of which now need process ids. Move them up and add `tab_pids()`.

First **delete** lines 2551-2561, i.e. exactly this block:

```python
          import subprocess

          def content_pids():
              try:
                  out = subprocess.run(
                      ["pgrep", "-af", "contentproc"],
                      capture_output=True, text=True, timeout=5).stdout.strip()
              except Exception as e:
                  return f"ERR: {e}"
              return out
```

Then **insert** this immediately after `tripwires = []` (line 712) and before the comment
`# bare launch -- no \`fonts\` key at all`:

```python
          # #83 / #82 process instrumentation. content_pids() is unchanged and
          # was moved up from the pid block further down -- arms (b2r), (j) and
          # (j2) all need it now, and it was defined after all three.
          import subprocess

          def content_pids():
              try:
                  out = subprocess.run(
                      ["pgrep", "-af", "contentproc"],
                      capture_output=True, text=True, timeout=5).stdout.strip()
              except Exception as e:
                  return f"ERR: {e}"
              return out

          def tab_pids():
              # Gecko puts a content process's remote type last on its command
              # line; ordinary page content is "tab". Returning a SET of pids
              # rather than the raw text is what lets an arm ASSERT "A and B
              # rendered in the same process" instead of assuming it -- #82 is a
              # per-process singleton cache, so an arm whose two contexts landed
              # in different processes measured nothing (code-recon B.3,
              # defect 3). A string return means pgrep itself failed; callers
              # must treat that as unmeasured, not as "different".
              raw = content_pids()
              if isinstance(raw, str) and raw.startswith("ERR:"):
                  return raw
              pids = set()
              for line in raw.splitlines():
                  parts = line.split()
                  if len(parts) >= 2 and parts[-1] == "tab":
                      pids.add(parts[0])
              return pids
```

- [ ] **Step 3: Add arm (b2r), the #83 discriminator**

Insert immediately after the closing rule of arm (b2) — the line
`# -----------------------------------------------------------` at 971 — and before the
`# Step 0:` comment block that follows.

```python
          # -----------------------------------------------------------
          # Arm (b2r): the #83 discriminator (code-recon C.4, hypothesis 1).
          # Same two contexts as arm (b2) directly above -- donor mac alive,
          # recipient win probed while it is still open -- with ONE variable
          # changed: `page = ctx.new_page()` runs BEFORE `ctx.add_init_script`,
          # so the first and only init-script invocation happens on the final
          # document, in the process that will render it.
          #
          # Hypothesis H1: the per-context list is process-local
          # (`static nsTHashMap sFontLists`, dom/base/FontListManager.cpp:14)
          # while the one-shot disable flag is cross-process
          # (RoverfoxStorageManager, FontListManager.cpp:79-81). A context whose
          # about:blank lands in P1 and whose real document lands in P2 installs
          # its list in P1, and P2 finds the setter already disabled, never
          # receives the list, and renders with HasFontList(ctx) == false --
          # where CamouIsFontAllowed returns true for every family
          # (gfxPlatformFontList.cpp:1232-1239). Under H1 this reorder makes the
          # leak disappear. Under H2 (gfxFontGroup::mUserContextId cached as 0,
          # gfxTextRun.cpp:1855-1875) ordering is irrelevant and the leak stays.
          #
          # WHAT WOULD MAKE THIS ARM GREEN WRONGLY (CLAUDE.md lesson 4):
          #  * Nothing about "win resolved no mac families" is self-validating.
          #    A context that never installed a list is allowed EVERYTHING, so
          #    that failure mode prints RED, not green -- and RED here reads as
          #    "H1 refuted", which is the wrong conclusion drawn from a broken
          #    setup. The arm therefore refuses to score at all unless the
          #    data-fl attribute proves the init script ran AND called
          #    setFontList on the very document that was measured. That is the
          #    exact reading error CLAUDE.md lesson 4 records twice: a global
          #    read back through page.evaluate (isolated world), and a one-shot
          #    setter already consumed by the about:blank invocation.
          #  * data-fl at about:blank must be ABSENT. With the reorder the init
          #    script is added after new_page(), so about:blank cannot carry it.
          #    A value there means the reorder did not take effect and this is
          #    arm (b2) under a different name -- scored as setup invalid.
          #  * The measurement itself is arm (b)'s own JS/PROBES, so a genuinely
          #    absent signal (nothing resolves, impossible family resolves) is
          #    still caught by check_signal below, exactly as in arm (b).
          B2R_INIT = ('(() => { const saw = (typeof window.setFontList === "function"); '
                      'let applied = false; '
                      'if (saw) { window.setFontList(%s); applied = true; } '
                      'const mark = () => { try { document.documentElement.setAttribute('
                      '"data-fl", JSON.stringify({saw: saw, applied: applied})); } catch (e) {} }; '
                      'mark(); document.addEventListener("DOMContentLoaded", mark); })()')

          b2r = {}
          b2r_pids = {}
          with sync_playwright() as pw:
              b2r_browser = pw.firefox.launch(
                  executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                  # EXACTLY arm (b2)'s launch (:901). Arm (b2) is this arm's
                  # control, and the discriminator is the reorder alone -- a
                  # second changed variable (fission.autostart, say) would make a
                  # difference between the two arms unattributable. Arms (j) and
                  # (j2) do change it, because there the spec asks for it and
                  # they carry their own controls.
                  firefox_user_prefs={"dom.ipc.processCount": 1},
                  env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
              b2r_ctxs = []
              for label in ("mac", "win"):
                  ctx = b2r_browser.new_context()
                  b2r_ctxs.append(ctx)
                  page = ctx.new_page()
                  b2r_pids[f"{label}_after_new_page"] = tab_pids()
                  fl_blank = page.evaluate(
                      '() => document.documentElement.getAttribute("data-fl")')
                  ctx.add_init_script(B2R_INIT % json.dumps(",".join(FONTS[label])))
                  page.goto(f"data:text/html,<h1>b2r-{label}</h1>")
                  b2r_pids[f"{label}_after_goto"] = tab_pids()
                  fl_doc = page.evaluate(
                      '() => document.documentElement.getAttribute("data-fl")')
                  b2r[label] = {"fl_blank": fl_blank, "fl_doc": fl_doc,
                                "res": page.evaluate(JS, PROBES)}
                  # The donor (mac) is deliberately NOT closed -- that is the one
                  # variable arm (b2) isolates, and this arm must keep it.
              for ctx in b2r_ctxs:
                  ctx.close()
              b2r_browser.close()

          for label in ("mac", "win"):
              print(f"  [b2r / {label}] data-fl at about:blank (expect None): "
                    f"{b2r[label]['fl_blank']!r}")
              print(f"  [b2r / {label}] data-fl on the document under test "
                    f"(expect saw=true applied=true): {b2r[label]['fl_doc']!r}")
              print(f"  [b2r / {label}] measure {b2r[label]['res']['measure']}")
          print(f"  [b2r / pids] {b2r_pids}")

          b2r_failures = []
          for label in ("mac", "win"):
              # check_signal hard-asserts, and this arm sits in the
              # collect-then-assert region: an AssertionError here would kill the
              # script before arms (e)-(k), (i), (j), (j2) and (h') ever run, and
              # a whole Phase B run would be lost to it. Collect instead.
              try:
                  check_signal(f"b2r / {label}", b2r[label]["res"])
              except AssertionError as exc:
                  b2r_failures.append(f"arm (b2r) no signal: {exc}")
              if b2r[label]["fl_blank"] is not None:
                  b2r_failures.append(
                      f"arm (b2r) setup invalid: {label}'s about:blank already carried "
                      f"data-fl={b2r[label]['fl_blank']!r}, so the init script applied before "
                      f"the page existed -- the reorder this arm tests did not take effect, "
                      f"and this is arm (b2) under another name.")
              try:
                  fl = json.loads(b2r[label]["fl_doc"]) if b2r[label]["fl_doc"] else None
              except ValueError:
                  fl = None
              if not fl or not fl.get("saw") or not fl.get("applied"):
                  b2r_failures.append(
                      f"arm (b2r) setup invalid: {label}'s document under test reports "
                      f"data-fl={b2r[label]['fl_doc']!r} -- setFontList was not seen or not "
                      f"called on the document that was measured. That context has no list, "
                      f"is therefore allowed every family, and any 'leak' below would be an "
                      f"artefact of this setup rather than #83.")
          if not b2r_failures:
              b2r_leaked = [f for f in MAC_ONLY if b2r["win"]["res"]["measure"][f]]
              if b2r_leaked:
                  b2r_failures.append(
                      f"arm (b2r)/#83: with the init script proven applied to the document "
                      f"under test (data-fl={b2r['win']['fl_doc']}), win STILL resolved "
                      f"macOS-only families {b2r_leaked} with the donor alive -- H1 is "
                      f"REFUTED; the leak survives the reorder and the cause is not process "
                      f"placement.")
          print(f"  (b2r) #83 discriminator (init script on the document under test):  "
                f"{'RED' if b2r_failures else 'GREEN'} -- "
                f"{b2r_failures or 'win saw none of the macOS-only families -- H1 CONFIRMED: the list is process-local and the leak is process placement, not a broken gate'}")
          if b2r_failures:
              tripwires.append(f"(b2r) #83 discriminator: {b2r_failures}")
          # -----------------------------------------------------------
```

Two names this arm reuses from earlier in the same script, both already in scope at line 971:
`JS` and `PROBES` (defined at `:626` and `:615`), and `check_signal(label, r)` (defined at
`:652`). `MAC_ONLY` is defined at `:613` and `FONTS` at `:610`.

---

- [ ] **Step 4a: Give `two_contexts_one_launch` optional prefs and pid sampling**

Replace the launch line and the two `page.goto` / `evaluate` pairs in
`two_contexts_one_launch` (starts at `:1915`). Keep the whole existing comment block intact —
it records why the pref is permanent. Change only these four places.

Replace the signature line:
```python
          def two_contexts_one_launch(list_a, list_b, js):
```
with:
```python
          def two_contexts_one_launch(list_a, list_b, js, extra_prefs=None):
```

Immediately after that line and before the existing `# Deliberately NOT one_page()` comment,
insert:
```python
              # extra_prefs is additive and defaults to nothing, so arm (i)'s
              # already-confirmed RED/GREEN pair (runs 33597181430 / 33597175086)
              # keeps the exact launch it was measured under. Only arm (j)
              # passes anything.
              prefs = {"dom.ipc.processCount": 1}
              if extra_prefs:
                  prefs.update(extra_prefs)
```

Replace the launch keyword:
```python
                      firefox_user_prefs={"dom.ipc.processCount": 1},
```
with:
```python
                      firefox_user_prefs=prefs,
```

Replace the tail of the function, from `page_a.goto(` to `return result_a, result_b`, with:
```python
                  page_a.goto("data:text/html,<h1>4b-a</h1>")
                  pids_a = tab_pids()
                  result_a = page_a.evaluate(js)

                  ctx_b = b.new_context()
                  ctx_b.add_init_script(
                      'if (typeof window.setFontList === "function") '
                      'window.setFontList(%s);' % json.dumps(",".join(list_b)))
                  page_b = ctx_b.new_page()
                  page_b.goto("data:text/html,<h1>4b-b</h1>")
                  pids_b = tab_pids()
                  result_b = page_b.evaluate(js)

                  b.close()
                  # A stays open for B's whole probe (no ctx_a.close()), which is
                  # the donor-alive shape #83 showed is the one that leaks.
                  return result_a, result_b, {"after_a": pids_a, "after_b": pids_b}
```

- [ ] **Step 4b: Update arm (i)'s call site (`:1992`)**

Replace:
```python
          i_a, i_b = two_contexts_one_launch(NO_CJK_PROBE, FONTS["win"], JS_4B)
```
with:
```python
          i_a, i_b, i_pids = two_contexts_one_launch(NO_CJK_PROBE, FONTS["win"], JS_4B)
          print(f"  [arm i / 4b] tab pids after A / after B: {i_pids}")
```
Arm (i)'s verdict logic is unchanged. It is not scored on process sharing: #81's negative
cache is process-wide but arm (i) already produces a verified RED/GREEN pair, and adding a
new refusal condition to a passing arm would be a change nothing asked for.

- [ ] **Step 4c: Repair arm (j) — positive identification instead of a floor**

Three edits inside arm (j) (`:2066`-`:2215`).

**(i) Replace the probe-list derivation at `:2127`-`:2128`:**
```python
          FFFD_YES_PROBE = fffd_working if fffd_working else FFFD_CANDIDATES
          FFFD_NO_PROBE = ["Arial", "Calibri", "Times New Roman"]
```
with:
```python
          # REPAIR (#82, 2026-09-09). The donor's list is exactly ["Tahoma"].
          # From the bisect in run 34240575679, Tahoma renders U+FFFD at 46.617
          # while Verdana and Segoe UI BOTH render it at 44.533 -- with more than
          # one family on the donor's list the leaked width cannot be attributed
          # to a specific face, so a leak and a coincidence look the same.
          # Malgun Gothic (48) is also unambiguous but is a CJK face whose
          # advance is more likely to collide with a fallback.
          FFFD_DONOR = ["Tahoma"]
          FFFD_NO_PROBE = ["Arial", "Calibri", "Times New Roman"]
          # Cross-check, printed not scored: the width Tahoma rendered U+FFFD at
          # in run 34240575679. A different number here is not a failure -- it
          # means the bundle or the build changed -- but it must be read before
          # anyone quotes 46.617 again (CLAUDE.md lesson 6).
          FFFD_TAHOMA_HISTORIC = 46.617
```

**(ii) Replace the last line of `JS_4C` (`:2168`-`:2169`), which currently reads:**
```python
            return {final: samples[samples.length - 1], samples: samples,
                    refs: refs, named: named, tofu: named['Arial']};
```
with:
```python
            // `tofu` is retained only as a printed diagnostic. It is NO LONGER
            // the scoring reference: both it and `final` route through U+FFFD
            // system fallback, so during a real leak the cache answers both
            // identically and the arm goes green for the bug it guards
            // (code-recon B.3, defect 1). Scoring is now positive
            // identification against the donor's own directly-named Tahoma
            // width, measured in the same run and the same process.
            return {final: samples[samples.length - 1], samples: samples,
                    refs: refs, named: named, tofu: named['Arial']};
```

**(iii) Replace everything from the call site at `:2172` down to the
`tripwires.append(f"(j) replacement-char cache leak (#82): {j_failures}")` line at `:2214`
with:**

```python
          # WHAT WOULD MAKE THIS ARM GREEN WRONGLY (CLAUDE.md lesson 4):
          #  1. The old floor comparison. `tofu = named['Arial']` and `final`
          #     both route through U+FFFD system fallback, so a cache hit
          #     answered both and `final != tofu` was false during a real leak.
          #     Replaced below by positive identification: B leaks iff B's
          #     automatic fallback measures the SAME width as the donor's own
          #     directly-named Tahoma, and the arm refuses to score unless that
          #     signature is proven different from B's own tofu floor.
          #  2. Donor and recipient in different content processes.
          #     mReplacementCharFallbackFamily is a member of gfxPlatformFontList,
          #     a per-process singleton, so a split pair tests nothing and would
          #     print GREEN. #83's process table (run 34008395471) showed
          #     dom.ipc.processCount=1 alone does not collapse them, so the pids
          #     are asserted, not assumed, and a split reports "unmeasured".
          #  3. The donor never populating the cache. Under a narrow list
          #     GlobalFontFallback can take the StartCmapLoadingFromFamily skip
          #     (gfxPlatformFontList.cpp:1581-1587) and `continue` past every
          #     family, leaving nothing to inherit. Turned off with
          #     gfx.font_rendering.fallback.async=false, and asserted: A's own
          #     automatic `final` must equal A's directly-named Tahoma width.
          j_a, j_b, j_pids = two_contexts_one_launch(
              FFFD_DONOR, FFFD_NO_PROBE, JS_4C,
              extra_prefs={"gfx.font_rendering.fallback.async": False,
                           "fission.autostart": False})
          j_sig = j_a["named"]["Tahoma"]      # the leak signature
          j_b_floor = j_b["named"]["Arial"]   # B's true tofu, no U+FFFD coverage
          print(f"  [arm j / #82] context A ({FFFD_DONOR}, donor, first in launch, stays open) "
                f"settled={j_a['final']} named-Tahoma={j_sig} named={j_a['named']} "
                f"refs={j_a['refs']} samples={j_a['samples']}")
          print(f"  [arm j / #82] context B ({FFFD_NO_PROBE}, no U+FFFD coverage, same launch, "
                f"AFTER A) settled={j_b['final']} own-tofu-floor={j_b_floor} "
                f"named={j_b['named']} refs={j_b['refs']} samples={j_b['samples']}")
          print(f"  [arm j / #82] tab pids after A / after B: {j_pids}")
          print(f"  [arm j / #82] cross-check (printed, not scored): donor Tahoma U+FFFD "
                f"width {j_sig} vs run 34240575679's {FFFD_TAHOMA_HISTORIC} -- "
                f"{'matches' if abs(j_sig - FFFD_TAHOMA_HISTORIC) < 0.01 else 'DIFFERS, do not quote the old number'}")

          j_failures = []
          if isinstance(j_pids["after_a"], str) or isinstance(j_pids["after_b"], str):
              j_failures.append(
                  f"arm (j)/#82 unmeasured: could not read the content-process table "
                  f"({j_pids}) -- #82's cache is a per-process singleton, so without the pids "
                  f"this arm cannot tell a working gate from two isolated processes.")
          elif (j_pids["after_b"] - j_pids["after_a"]) or not j_pids["after_a"]:
              # "No NEW tab pid appeared for B", not set equality: a lingering
              # about:blank process that exits between the two samples would make
              # equality false forever and the arm would read "unmeasured" on
              # every run, including ones that did share a process.
              j_failures.append(
                  f"arm (j)/#82 unmeasured: a new content process appeared for B. Tab pids were "
                  f"{sorted(j_pids['after_a'])} after A and {sorted(j_pids['after_b'])} after "
                  f"B, so donor and recipient did not share the gfxPlatformFontList singleton "
                  f"that holds mReplacementCharFallbackFamily. Not a verdict either way.")
          elif "Tahoma" not in fffd_working:
              j_failures.append(
                  f"arm (j)/#82 setup invalid: Tahoma is not among the families that "
                  f"demonstrably resolve U+FFFD in this build ({fffd_working or 'NONE'}, "
                  f"widths {fffd_bisect['widths']}, tofu {fffd_bisect['tofu']}). The donor "
                  f"cannot populate the cache, so there is nothing for B to inherit.")
          elif abs(j_a["final"] - j_sig) >= 0.01:
              j_failures.append(
                  f"arm (j)/#82 setup invalid: the donor's AUTOMATIC U+FFFD fallback settled "
                  f"at {j_a['final']}, not at its own directly-named Tahoma width ({j_sig}), "
                  f"so mReplacementCharFallbackFamily was never populated with Tahoma and "
                  f"there is nothing for context B to inherit. Check whether "
                  f"gfx.font_rendering.fallback.async=false actually applied.")
          elif abs(j_sig - j_b_floor) < 0.01:
              j_failures.append(
                  f"arm (j)/#82 control invalid: the leak signature ({j_sig}, the donor's "
                  f"Tahoma) equals context B's own tofu floor ({j_b_floor}, its named Arial), "
                  f"so a leak and a correct block would read identically. This arm cannot "
                  f"discriminate on this build.")
          elif abs(j_b["final"] - j_sig) < 0.01:
              j_failures.append(
                  f"arm (j)/#82: REPLACEMENT-CHAR CACHE LEAK (#82) -- context B "
                  f"({FFFD_NO_PROBE}, none of which cover U+FFFD) settled U+FFFD at "
                  f"{j_b['final']}, which is the donor's own Tahoma width ({j_sig}) and not "
                  f"B's tofu floor ({j_b_floor}). Both contexts shared tab process(es) "
                  f"{sorted(j_pids['after_a'])}. B rendered a REAL glyph from a family it was "
                  f"never allowed, inherited through gfxPlatformFontList's process-wide "
                  f"mReplacementCharFallbackFamily, which is read at "
                  f"gfxPlatformFontList.cpp:1328-1348 with no CamouIsFontAllowed check.")
          j_ok_msg = (f"context B settled U+FFFD at {j_b['final']}, which is NOT the donor's "
                      f"Tahoma ({j_sig}); the donor did populate the cache "
                      f"(A settled {j_a['final']}), the two shared "
                      f"process(es) {sorted(j_pids['after_a']) if not isinstance(j_pids['after_a'], str) else j_pids['after_a']}, "
                      f"and B's own floor is {j_b_floor}")
          print(f"  (j) replacement-char cache leak (#82):  {'RED' if j_failures else 'GREEN'} "
                f"-- {j_failures or j_ok_msg}")
          if j_failures:
              tripwires.append(f"(j) replacement-char cache leak (#82): {j_failures}")
```

- [ ] **Step 4d: Repair arm (j2) — same six changes, adapted to a bare donor**

Arm (j2)'s donor is bare by construction (nothing calls `setFontList` on it), which is the
whole point of the arm, so repair item 1 (donor list `["Tahoma"]`) does not apply to it.
The leak signature is instead **derived** from the donor's own numbers: whichever of A's
named families measures A's settled width is the face A's fallback landed on.

**(i) In `two_contexts_bare_then_narrow` (`:2696`), add prefs and pid sampling.** Replace the
signature line:
```python
              def two_contexts_bare_then_narrow(list_b, js):
```
with:
```python
              def two_contexts_bare_then_narrow(list_b, js, extra_prefs=None):
                  prefs = {"dom.ipc.processCount": 1}
                  if extra_prefs:
                      prefs.update(extra_prefs)
```
Replace its launch keyword:
```python
                          firefox_user_prefs={"dom.ipc.processCount": 1},
```
with:
```python
                          firefox_user_prefs=prefs,
```
and replace its tail, from `page_a.goto("data:text/html,<h1>4b-bare-a</h1>")` to
`return result_a, result_b`, with:
```python
                      page_a.goto("data:text/html,<h1>4b-bare-a</h1>")
                      pids_a = tab_pids()
                      result_a = page_a.evaluate(js)

                      ctx_b = b.new_context()
                      ctx_b.add_init_script(
                          'if (typeof window.setFontList === "function") '
                          'window.setFontList(%s);' % json.dumps(",".join(list_b)))
                      page_b = ctx_b.new_page()
                      page_b.goto("data:text/html,<h1>4b-bare-b</h1>")
                      pids_b = tab_pids()
                      result_b = page_b.evaluate(js)

                      b.close()
                      return result_a, result_b, {"after_a": pids_a, "after_b": pids_b}
```

**(ii) Replace everything from the call site at `:2732` down to the closing
`print(f"  (j2) bare-context replacement-char cache leak (#82): ...")` block with:**

```python
              # WHAT WOULD MAKE THIS ARM GREEN WRONGLY (CLAUDE.md lesson 4):
              # identical to arm (j)'s list, with one difference. A bare donor
              # has no list, so the leak signature cannot be named in advance --
              # it is DERIVED here from the donor's own `named` dict: the family
              # whose directly-named U+FFFD width equals the donor's settled
              # width is the face the cache now holds. If no named family
              # matches, the arm cannot identify what the donor resolved and
              # says so rather than falling back to a floor comparison, which is
              # the exact defect this repair removes.
              j2_a, j2_b, j2_pids = two_contexts_bare_then_narrow(
                  FFFD_NO_PROBE, JS_4C,
                  extra_prefs={"gfx.font_rendering.fallback.async": False,
                               "fission.autostart": False})
              j2_sig_families = [fam for fam, w in j2_a["named"].items()
                                 if abs(w - j2_a["final"]) < 0.01]
              j2_b_floor = j2_b["named"]["Arial"]
              print(f"  [arm j2 / #82] context A (bare, no setFontList call at all, first in "
                    f"launch, stays open) settled={j2_a['final']} named={j2_a['named']} "
                    f"refs={j2_a['refs']} samples={j2_a['samples']}")
              print(f"  [arm j2 / #82] the donor's settled width matches these named families: "
                    f"{j2_sig_families or 'NONE'}")
              print(f"  [arm j2 / #82] context B ({FFFD_NO_PROBE}, no U+FFFD coverage, same "
                    f"launch, AFTER A) settled={j2_b['final']} own-tofu-floor={j2_b_floor} "
                    f"named={j2_b['named']} refs={j2_b['refs']} samples={j2_b['samples']}")
              print(f"  [arm j2 / #82] tab pids after A / after B: {j2_pids}")

              if isinstance(j2_pids["after_a"], str) or isinstance(j2_pids["after_b"], str):
                  j2_failures.append(
                      f"arm (j2)/#82 unmeasured: could not read the content-process table "
                      f"({j2_pids}); #82's cache is a per-process singleton.")
              elif (j2_pids["after_b"] - j2_pids["after_a"]) or not j2_pids["after_a"]:
                  # Same "no NEW tab pid" test as arm (j), for the same reason.
                  j2_failures.append(
                      f"arm (j2)/#82 unmeasured: a new content process appeared for B. Tab pids were "
                      f"{sorted(j2_pids['after_a'])} after A and {sorted(j2_pids['after_b'])} "
                      f"after B, so donor and recipient did not share the gfxPlatformFontList "
                      f"singleton. Not a verdict either way.")
              elif not j2_sig_families:
                  j2_failures.append(
                      f"arm (j2)/#82 setup invalid: the bare donor settled U+FFFD at "
                      f"{j2_a['final']}, which matches none of the families it named "
                      f"({j2_a['named']}). The face now in mReplacementCharFallbackFamily "
                      f"cannot be identified, so no positive-identification verdict is "
                      f"available and this arm will not fall back to a floor comparison.")
              elif abs(j2_a["final"] - j2_b_floor) < 0.01:
                  j2_failures.append(
                      f"arm (j2)/#82 control invalid: the leak signature ({j2_a['final']}, "
                      f"from {j2_sig_families}) equals context B's own tofu floor "
                      f"({j2_b_floor}), so a leak and a correct block would read identically.")
              elif abs(j2_b["final"] - j2_a["final"]) < 0.01:
                  j2_failures.append(
                      f"arm (j2)/#82: REPLACEMENT-CHAR CACHE LEAK (#82) CONFIRMED via the "
                      f"bare-context population path -- context B ({FFFD_NO_PROBE}, none of "
                      f"which cover U+FFFD) settled U+FFFD at {j2_b['final']}, the same width "
                      f"the bare donor settled at ({j2_a['final']}, identified as "
                      f"{j2_sig_families}) and not B's own floor ({j2_b_floor}). Both shared "
                      f"tab process(es) {sorted(j2_pids['after_a'])}. A bare context -- the "
                      f"production shape of one nobody ever called setFontList on, which "
                      f"CamouIsFontAllowed treats exactly like userContextId 0 -- populated "
                      f"the process-wide cache and B inherited a real glyph from a family it "
                      f"was never allowed.")
              j2_ok_msg = (f"context B settled U+FFFD at {j2_b['final']}, which is NOT the "
                           f"bare donor's {j2_a['final']} ({j2_sig_families}); B's own floor "
                           f"is {j2_b_floor}")
              print(f"  (j2) bare-context replacement-char cache leak (#82):  "
                    f"{'RED' if j2_failures else 'GREEN'} -- {j2_failures or j2_ok_msg}")
```

The `if not bare_working:` branch above it (`:2677`-`:2694`) is unchanged: it is still the
stop condition when nothing resolves U+FFFD under a bare context, and it still appends to the
same `j2_failures` list, which is initialised at `:2676` and read by the
`if j2_failures: tripwires.append(...)` line at `:2766`-`:2767`.

---

- [ ] **Step 4e: Add arm (i2), #81's ordering case**

Arm (i) tests install, render, install, render — and Task 1's comment on #81 says in as many
words that the clear-on-install fix does not generalise past that sequence. Without an arm for
the other order, `Closes #81` in Task 9 would rest on evidence this plan itself calls
insufficient. Arm (i2) is arm (i) with both installs moved ahead of both renders.

Insert immediately after arm (i)'s `tripwires.append(f"(i) negative fallback cache (#81): ...")`
line (`:2046`) and before the rule that closes the arm.

```python
          # -----------------------------------------------------------
          # Arm (i2): #81 in the ordinary caller shape. Arm (i) above installs
          # A's list, renders A, installs B's list, renders B -- and B's install
          # runs ClearCodepointsWithNoFonts() AFTER A's miss was written, so the
          # clear-on-install fix covers it. A caller that sets up its contexts
          # before navigating produces the other order: both installs, then both
          # renders. Both clears are spent before A's gated miss reaches
          # gfxPlatformFontList.cpp:1403, nothing clears the cache between A's
          # render and B's, and B reads tofu for a codepoint its own list covers.
          #
          # This is why the fix in this PR is on the READ path: a context with
          # its own list neither honours a hit in gfxFontGroup::FindFontForChar
          # nor records its own misses. That has no ordering dependency.
          #
          # WHAT WOULD MAKE THIS ARM GREEN WRONGLY (CLAUDE.md lesson 4):
          #  * Comparing B against B's OWN generic refs. FONTS['win'] broadly
          #    covers CJK, so B's monospace/sans-serif/serif legitimately reach
          #    the same real face B's gate finds -- both correct, and "differs
          #    from B's refs" is false for a WORKING fix. Arm (i) hit exactly
          #    that false AssertionError on its first real run. The floor is A's
          #    settled width instead: A's list has zero CJK anywhere, asserted
          #    below, so it is a genuine "nothing rendered" baseline.
          #  * Both contexts in different processes. mCodepointsWithNoFonts is a
          #    per-process member, so a split pair cannot poison anything and
          #    would print GREEN. The tab pids are asserted, not assumed.
          #  * A never actually missing. If A's own settled width is NOT its own
          #    tofu floor, A resolved something and wrote no miss, so there is
          #    nothing for B to inherit -- reported as setup invalid.
          def two_contexts_installs_first(list_a, list_b, js, extra_prefs=None):
              # Deliberately NOT two_contexts_one_launch(): that helper evaluates
              # A before B's context exists, which is the sequence arm (i)
              # already covers and the one the clear-on-install fix handles.
              prefs = {"dom.ipc.processCount": 1}
              if extra_prefs:
                  prefs.update(extra_prefs)
              with sync_playwright() as pw:
                  b = pw.firefox.launch(
                      executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                      firefox_user_prefs=prefs,
                      env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
                  ctx_a = b.new_context()
                  ctx_a.add_init_script(
                      'if (typeof window.setFontList === "function") '
                      'window.setFontList(%s);' % json.dumps(",".join(list_a)))
                  page_a = ctx_a.new_page()
                  page_a.goto("data:text/html,<h1>i2-a</h1>")

                  ctx_b = b.new_context()
                  ctx_b.add_init_script(
                      'if (typeof window.setFontList === "function") '
                      'window.setFontList(%s);' % json.dumps(",".join(list_b)))
                  page_b = ctx_b.new_page()
                  page_b.goto("data:text/html,<h1>i2-b</h1>")
                  pids = tab_pids()

                  # Both installs are done, so both clears are spent. Only now
                  # does anything render.
                  result_a = page_a.evaluate(js)
                  result_b = page_b.evaluate(js)

                  b.close()
                  return result_a, result_b, {"after_both": pids}

          i2_a, i2_b, i2_pids = two_contexts_installs_first(
              NO_CJK_PROBE, FONTS["win"], JS_4B)
          i2_a_tofu = i2_a["final"] in i2_a["refs"].values()
          i2_b_tofu = i2_b["final"] == i2_a["final"]
          print(f"  [arm i2 / #81] context A (no-CJK list, installed first, rendered first) "
                f"settled={i2_a['final']} refs={i2_a['refs']} samples={i2_a['samples']}")
          print(f"  [arm i2 / #81] context B (FONTS['win'], installed BEFORE A rendered) "
                f"settled={i2_b['final']} refs={i2_b['refs']} samples={i2_b['samples']}")
          print(f"  [arm i2 / #81] tab pids after both navigations: {i2_pids}")

          i2_failures = []
          if isinstance(i2_pids["after_both"], str) or len(i2_pids["after_both"]) != 1:
              i2_failures.append(
                  f"arm (i2)/#81 unmeasured: tab pids were {i2_pids['after_both']}, not a "
                  f"single shared process. mCodepointsWithNoFonts is a per-process member, so "
                  f"A's miss cannot reach B and this arm tests nothing.")
          elif not i2_a_tofu:
              i2_failures.append(
                  f"arm (i2)/#81 setup invalid: context A's no-CJK list ({NO_CJK_PROBE}) "
                  f"settled U+6F22 at {i2_a['final']}, which is not one of its own generic "
                  f"refs ({i2_a['refs']}) -- A resolved something, wrote no miss, and there is "
                  f"nothing for B to inherit.")
          elif i2_b_tofu:
              i2_failures.append(
                  f"arm (i2)/#81: NEGATIVE FALLBACK CACHE BUG, ordering case -- both contexts "
                  f"installed their lists before either rendered, so both "
                  f"ClearCodepointsWithNoFonts() calls were spent before context A's gated "
                  f"miss was written at gfxPlatformFontList.cpp:1403. Context B "
                  f"(FONTS['win'], which covers U+6F22) settled at {i2_b['final']}, the same "
                  f"width A's zero-CJK list produced -- B rendered tofu for a codepoint its "
                  f"own list covers, and B's gate never ran because "
                  f"SkipFontFallbackForChar answered first. The clear-on-install fix cannot "
                  f"see this order; the read-path check is what closes it.")
          print(f"  (i2) negative fallback cache, ordering case (#81):  "
                f"{'RED' if i2_failures else 'GREEN'} -- "
                f"{i2_failures or f'context B rendered its own glyph ({i2_b['final']}) rather than A tofu floor ({i2_a['final']}), in tab process {i2_pids['after_both']}'}")
          if i2_failures:
              tripwires.append(f"(i2) negative fallback cache, ordering case (#81): {i2_failures}")
          # -----------------------------------------------------------
```

`NO_CJK_PROBE` (`:1913`) and `JS_4B` (`:1969`-`:1990`) are both already in scope at `:2046`.

- [ ] **Step 5: Add arm (k), the #80 render probe**

`fontTools` is **not** currently installed in this step (verified: the only `pip install` in
the `#44` step is `pip install --quiet 'playwright==1.55.0'` at `:605`; every `fontTools`
mention in the file is prose describing work done locally). Change `:605` to:

```yaml
          pip install --quiet 'playwright==1.55.0' fonttools
```

Insert arm (k) immediately after the web-font block, i.e. after the final `else:` branch's
last `print(...)` that ends `"...or trying a woff2 payload.")` and before the
`# -----------------------------------------------------------` that opens arm (i) at
`:1883`. Indentation is 10 spaces, at the same level as the `import base64, glob` line.

```python
          # -----------------------------------------------------------
          # Arm (k): #80's RENDER half. The web-font block above measured probe
          # width 761.33 in BOTH launches -- only the monospace reference moved
          # (#80's own recorded numbers). Its probe font was DejaVuSans.ttf,
          # which IS a bundled family, so reference and measurement could
          # resolve to the same typeface and "rendered? False" was never
          # established (CLAUDE.md lesson 4; code-recon A.1). Only the
          # `status = 'error'` half is supported by that evidence.
          #
          # This arm removes the coincidence. The probe font is built here at
          # run time, has no twin anywhere in bundle/fonts, and carries a
          # deliberately absurd advance: unitsPerEm 1000 with glyph 'a' advancing
          # 2000 units, so at 48px each 'a' advances 48 * 2000/1000 = 96px and a
          # 20-character string measures exactly 1920. "Did it render" is one
          # exact number and needs no reference face at all.
          #
          # WHAT WOULD MAKE THIS ARM GREEN WRONGLY (CLAUDE.md lesson 4):
          #  1. A payload that fails to build or fails to decode gives status
          #     'error' and a fallback width -- indistinguishable from the gate
          #     refusing it. The BARE launch is the control: no `fonts` key, no
          #     setFontList call, so IsFontAllowed answers true for everything
          #     (FontFaceImpl.h). If the face does not render THERE, the probe
          #     is at fault and the arm reports "probe invalid" rather than a
          #     #80 verdict.
          #  2. 1920 arriving from a fallback face would require that face to
          #     have a two-em advance for 'a'. Ruled out explicitly: the
          #     monospace baseline for the same string is measured and must not
          #     equal 1920.
          #  3. Reading `document.fonts` for the wrong face. The family name is
          #     matched with the quote-stripping the existing web-font probe
          #     uses, because FontFace.family serialises WITH quotes -- the
          #     defect that made every arm (e) face read 'error' before #84.
          K_FAMILY = "CamouProbeK"
          K_EXPECT = 1920.0

          def build_probe_k():
              """A one-glyph TTF with a two-em advance. Returns a data: URI, or
              None if fontTools could not build it (reported, never silent)."""
              import io
              import base64 as _b64
              from fontTools.fontBuilder import FontBuilder
              from fontTools.pens.ttGlyphPen import TTGlyphPen
              fb = FontBuilder(1000, isTTF=True)
              fb.setupGlyphOrder([".notdef", "a"])
              fb.setupCharacterMap({0x61: "a"})
              pen = TTGlyphPen(None)
              pen.moveTo((100, 0))
              pen.lineTo((100, 700))
              pen.lineTo((900, 700))
              pen.lineTo((900, 0))
              pen.closePath()
              fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "a": pen.glyph()})
              fb.setupHorizontalMetrics({".notdef": (2000, 0), "a": (2000, 100)})
              fb.setupHorizontalHeader(ascent=800, descent=-200)
              fb.setupNameTable({
                  "familyName": K_FAMILY,
                  "styleName": "Regular",
                  "uniqueFontIdentifier": K_FAMILY + "-Regular-camoufox-probe",
                  "fullName": K_FAMILY + " Regular",
                  "psName": K_FAMILY + "-Regular",
                  "version": "1.000",
              })
              fb.setupOS2(sTypoAscender=800, sTypoDescender=-200,
                          usWinAscent=800, usWinDescent=200)
              fb.setupPost()
              buf = io.BytesIO()
              fb.save(buf)
              return "data:font/ttf;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")

          k_uri, k_build_error = None, None
          try:
              k_uri = build_probe_k()
          except Exception as exc:
              k_build_error = f"{type(exc).__name__}: {exc}"

          JS_K = """async (fontDataUri) => {
            const FAMILY = 'CamouProbeK';
            const sheet = document.createElement('style');
            sheet.textContent =
                '@font-face { font-family: ' + FAMILY + '; src: url("' + fontDataUri + '"); }';
            document.head.appendChild(sheet);
            document.body.offsetHeight;
            await document.fonts.ready;
            const face = [...document.fonts].find(
                f => f.family.replace(/^["\']|["\']$/g, '') === FAMILY);
            const c = document.createElement('canvas').getContext('2d');
            const s = 'aaaaaaaaaaaaaaaaaaaa';   // 20 glyphs -> 1920 at 48px
            c.font = '48px monospace';
            const baseline = c.measureText(s).width;
            c.font = '48px "' + FAMILY + '", monospace';
            const probeWidth = c.measureText(s).width;
            return {status: face ? face.status : 'NO_FACE_FOUND',
                    probeWidth: probeWidth, baseline: baseline};
          }"""

          def k_launch(with_list, js, arg):
              # Its own launcher: one_page_webfont / one_page_webfont_bare are
              # nested inside the web-font block's conditionals and are not in
              # scope here.
              with sync_playwright() as pw:
                  b = pw.firefox.launch(
                      executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                      env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
                  ctx = b.new_context()
                  if with_list:
                      ctx.add_init_script(
                          'if (typeof window.setFontList === "function") '
                          'window.setFontList(%s);' % json.dumps(",".join(FONTS["mac"])))
                  page = ctx.new_page()
                  page.goto("data:text/html,<h1>k</h1>")
                  result = page.evaluate(js, arg)
                  b.close()
                  return result

          k_failures = []
          if k_uri is None:
              k_failures.append(
                  f"arm (k) probe invalid: fontTools could not build the probe face "
                  f"({k_build_error}) -- no #80 verdict is available from this run.")
          else:
              k_list = k_launch(True, JS_K, k_uri)
              k_bare = k_launch(False, JS_K, k_uri)
              print(f"  [arm k / #80] per-context list (FONTS['mac'], which cannot contain "
                    f"{K_FAMILY!r}): status={k_list['status']!r} width={k_list['probeWidth']} "
                    f"monospace baseline={k_list['baseline']} (expect {K_EXPECT} after the fix)")
              print(f"  [arm k / #80] bare launch (control -- IsFontAllowed allows everything): "
                    f"status={k_bare['status']!r} width={k_bare['probeWidth']} "
                    f"monospace baseline={k_bare['baseline']}")
              if abs(k_bare["probeWidth"] - K_EXPECT) >= 0.01:
                  k_failures.append(
                      f"arm (k) probe invalid: under the BARE launch -- no `fonts` key and no "
                      f"setFontList call, so IsFontAllowed answers true for every family -- "
                      f"the probe measured {k_bare['probeWidth']}, not {K_EXPECT}. The payload "
                      f"or the @font-face rule is at fault, not the gate, and this arm cannot "
                      f"say anything about #80 until the bare control renders.")
              elif abs(k_bare["baseline"] - K_EXPECT) < 0.01:
                  k_failures.append(
                      f"arm (k) control invalid: the monospace baseline for the same string is "
                      f"also {k_bare['baseline']}, so {K_EXPECT} no longer identifies the "
                      f"probe face.")
              else:
                  if k_list["status"] != "loaded":
                      k_failures.append(
                          f"arm (k)/#80: a url() web font under a per-context list reports "
                          f"document.fonts status {k_list['status']!r}, not 'loaded'. The same "
                          f"bytes report {k_bare['status']!r} under the bare launch, so this "
                          f"is the family-name gate refusing a family the page invented, not a "
                          f"load failure. FontFaceImpl::SetStatus / FontFace::Status().")
                  if abs(k_list["probeWidth"] - K_EXPECT) >= 0.01:
                      k_failures.append(
                          f"arm (k)/#80: the same url() web font did not RENDER under a "
                          f"per-context list -- width {k_list['probeWidth']}, expected "
                          f"{K_EXPECT}, monospace baseline {k_list['baseline']} -- while it "
                          f"rendered at {k_bare['probeWidth']} under the bare launch. This is "
                          f"the render half #80 never established.")
          print(f"  (k) url() web font under a fonts list (#80):  "
                f"{'RED' if k_failures else 'GREEN'} -- "
                f"{k_failures or f'status loaded and width {K_EXPECT} under both launches'}")
          if k_failures:
              tripwires.append(f"(k) url() web font under a fonts list (#80): {k_failures}")
          # -----------------------------------------------------------
```

- [ ] **Step 6: Add arm (h'), the #88 width match, and the MN8 tripwire**

**(i) Add an argument-taking single-page helper.** Insert immediately after `one_page`'s
definition ends (the `return result` at the end of the block starting `:1382`) and before the
`e = {"mac": one_page(...)` line:

```python
          def one_page_arg(fonts_key, js, arg):
              # one_page() with an argument for page.evaluate(). Same launch,
              # same context, same single page.
              with sync_playwright() as pw:
                  b = pw.firefox.launch(
                      executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
                      env={**os.environ, "CAMOU_CONFIG": json.dumps({})})
                  ctx = b.new_context()
                  ctx.add_init_script(
                      'if (typeof window.setFontList === "function") '
                      'window.setFontList(%s);' % json.dumps(",".join(FONTS[fonts_key])))
                  page = ctx.new_page()
                  page.goto("data:text/html,<h1>f</h1>")
                  result = page.evaluate(js, arg)
                  b.close()
                  return result
```

**(ii) Extend the arm (h) control clash check (MN8).** Replace the `h_ref_clash` assignment
at `:1720`-`:1723`:
```python
          h_ref_clash = [name for name, w in (("monospace baseline", g["win"]["baseline48"]),
                                              ("sans-serif", h["win"]["sans"]),
                                              ("serif", h["win"]["serif"]))
                         if segoe_ref == w]
```
with:
```python
          # MN8 (from PR #84's re-review): the previous version checked segoe_ref
          # only against the WIN context's generics, so a mac-side clash --
          # segoe_ref equal to a width the mac context can reach for free --
          # would let the mac arm read "resolved Segoe UI" for a face that is
          # simply the mac generic. The mac context is where the refusal is
          # under test, so its own generics have to be in the clash set too.
          h_ref_clash = [name for name, w in (
                             ("win monospace baseline", g["win"]["baseline48"]),
                             ("win sans-serif", h["win"]["sans"]),
                             ("win serif", h["win"]["serif"]),
                             ("mac monospace baseline", h["mac"]["baseline"]),
                             ("mac sans-serif", h["mac"]["sans"]),
                             ("mac serif", h["mac"]["serif"]))
                         if segoe_ref == w]
```

**(iii) Add arm (h').** Insert immediately after the arm (e)-(h) summary block, i.e. after the
line that prints `      win: local('Segoe UI')=...` and before the
`# Web-font measurement (out of scope for this task ...` comment.

```python
          # -----------------------------------------------------------
          # Arm (h'): identify the 375.70001220703125 face (#88). Arm (h) above
          # proved the gate FIRED for both mac probes -- the diag build's
          # CAMOU-H trace logged ctx=6 hasList=1 allowed=0 -- and the text still
          # rendered at 375.70001220703125, which matches nothing else in run
          # 34213805428: not the real Segoe UI (448.4 in the win context), not
          # the generics (507.5), not Helvetica Neue (441.45), not Tahoma
          # (436.27). Method 1 of #88: measure every family the macOS bundle
          # carries, in the same mac context, at the same size and stack, and
          # print whichever matches. No rebuild.
          #
          # WHAT WOULD MAKE THIS PRINT A WRONG ANSWER (CLAUDE.md lesson 4):
          #  * A family that does NOT resolve measures the monospace baseline,
          #    because the probe stack is '48px "F", monospace' -- the same
          #    stack arm (h) uses. So a match must be reported together with
          #    whether that width equals the baseline; if it does, the "match"
          #    is just the fallback and names nothing.
          #  * .ttc files hold several faces and TTFont() raises on them, so a
          #    silent except would drop 33 of the 61 bundle entries and let the
          #    arm report "no match" when the answer was in the files it
          #    skipped. Collections are opened with TTCollection and every
          #    failure is counted and printed.
          #  * This is a DIAGNOSTIC. It appends to no tripwire and changes no
          #    verdict; it prints, and #88 is answered from what it prints.
          H88_TARGET = 375.70001220703125

          def mac_bundle_families():
              from fontTools.ttLib import TTFont, TTCollection
              fams, errs = set(), []
              root = "bundle/fonts/macos"
              for dirpath, _dirnames, filenames in os.walk(root):
                  for fn in filenames:
                      p = os.path.join(dirpath, fn)
                      try:
                          if fn.lower().endswith(".ttc"):
                              faces = list(TTCollection(p).fonts)
                          else:
                              faces = [TTFont(p, fontNumber=0, lazy=True)]
                      except Exception as exc:
                          errs.append(f"{fn}: {type(exc).__name__}")
                          continue
                      for face in faces:
                          try:
                              for rec in face["name"].names:
                                  # 1 = family, 16 = typographic family
                                  if rec.nameID in (1, 16):
                                      s = rec.toUnicode()
                                      if s:
                                          fams.add(s)
                          except Exception as exc:
                              errs.append(f"{fn}: name table: {type(exc).__name__}")
              return sorted(fams), errs

          JS_HP = """(families) => {
            const c = document.createElement('canvas').getContext('2d');
            const s48 = 'mmmmmmmmmmlli';
            const widths = {};
            for (const f of families) {
              c.font = '48px "' + f + '", monospace';
              widths[f] = c.measureText(s48).width;
            }
            for (const gname of ['monospace', 'sans-serif', 'serif']) {
              c.font = '48px ' + gname;
              widths['generic:' + gname] = c.measureText(s48).width;
            }
            return widths;
          }"""

          hp_families, hp_errs = mac_bundle_families()
          print(f"  [arm h' / #88] enumerated {len(hp_families)} family names from "
                f"bundle/fonts/macos; {len(hp_errs)} file(s) could not be read: {hp_errs}")
          if not hp_families:
              print("  [arm h' / #88] SKIP: no family names could be extracted -- the "
                    "identification cannot run, #88 falls back to its method 2 (log the "
                    "resolved gfxFontEntry after refusal) in a later build.")
          else:
              hp = one_page_arg("mac", JS_HP, hp_families)
              hp_baseline = hp.get("generic:monospace")
              hp_matches = [(f, w) for f, w in hp.items()
                            if not f.startswith("generic:")
                            and abs(w - H88_TARGET) < 0.01]
              print(f"  [arm h' / #88] mac-context generics: monospace={hp_baseline} "
                    f"sans-serif={hp.get('generic:sans-serif')} serif={hp.get('generic:serif')}")
              print(f"  [arm h' / #88] target {H88_TARGET}; families within 0.01: "
                    f"{hp_matches or 'NO MATCH'}")
              if hp_baseline is not None and abs(hp_baseline - H88_TARGET) < 0.01:
                  print(f"  [arm h' / #88] WARNING: the mac monospace baseline is itself "
                        f"{hp_baseline}, so every unresolved family matches the target and "
                        f"the list above names nothing.")
              elif hp_matches:
                  print(f"  [arm h' / #88] ANSWER: local('Segoe UI') in the mac context "
                        f"resolves to {[f for f, _ in hp_matches]}. Arm (h)'s verdict scores "
                        f"only 'is this the Segoe UI width', so this face passes it today; "
                        f"whether it is an expected fallback or a leak is #88's decision.")
              else:
                  print(f"  [arm h' / #88] ANSWER: {H88_TARGET} matches no family the macOS "
                        f"bundle carries, so the face is not a bundled mac family. #88 falls "
                        f"back to its method 2 (log the resolved gfxFontEntry after refusal "
                        f"in LookupInSharedFaceNameList), which needs a build.")
          # -----------------------------------------------------------
```

---

- [ ] **Step 7: Update `EXPECTED_RED` (`:2777`)**

Replace:
```python
          EXPECTED_RED = {
              "(b2)": "#83, cross-context font leak, donor-alive; unfixed",
              "(j)": "#82, U+FFFD cache; setup has never reproduced the leak",
              "(j2)": "#82, same, bare-context variant",
          }
```
with:
```python
          EXPECTED_RED = {
              "(b2)": "#83, cross-context font leak, donor-alive; unfixed",
              "(b2r)": "#83 DISCRIMINATOR, not a triaged defect -- a RED here is the "
                       "measurement, and its own printed line is what the gate is read "
                       "from. Listed so the run's later steps still execute; removed in "
                       "Phase D once #83 is decided",
              "(j)": "#82, U+FFFD cache; arm repaired 2026-09-09 to score by positive "
                     "identification against the donor's own Tahoma width",
              "(j2)": "#82, same, bare-context variant",
              "(i2)": "#81 ordering case -- both lists installed before either context "
                      "renders, which clear-on-install cannot see; unfixed",
              "(k)": "#80, url() web fonts refused when a fonts list is configured; unfixed",
          }
```

`(b2r)` is listed here **only** so a RED does not fail the step and skip the four steps that
follow it (`record_video`, `Integration suite`, `Detector-site smoke`, `Upload results`).
The triage line it produces is not the gate. The gate is the arm's own
`(b2r) #83 discriminator: ...` line, read in Step 10.

The key match uses `t.startswith(k)`, and `"(b2r) ...".startswith("(b2)")` is false, so
`(b2)` and `(b2r)` do not collide.

- [ ] **Step 8: Check, then commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml \
  "$TMPDIR/smoke-py-after"
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml')); print('YAML OK')"
git diff --stat .github/workflows/smoke.yml
```
Expected: every block `OK` and `N block(s), 0 failed`; `YAML OK`; a single changed file with
roughly 420 insertions and 30 deletions. If `check_smoke_python.py` reports a failure, fix the
block it names — it prints the workflow line the heredoc opened at.

Then confirm no arm was orphaned:
```bash
grep -c 'tripwires.append' .github/workflows/smoke.yml
grep -n 'def two_contexts_one_launch\|def two_contexts_bare_then_narrow\|def two_contexts_installs_first\|def tab_pids\|def one_page_arg\|def build_probe_k\|def mac_bundle_families\|def k_launch' .github/workflows/smoke.yml
grep -c 'import subprocess' .github/workflows/smoke.yml
```
Expected: `tripwires.append` count rises from 9 to 12 (arms `(b2r)`, `(i2)` and `(k)` are the
new ones; `(h')` deliberately appends nothing); all eight definitions present exactly once;
`import subprocess` exactly `1` (the hoisted copy, with the original deleted).

```bash
git add .github/workflows/smoke.yml
git commit -m "measure(#83 #82 #81 #80 #88): smoke arms (b2r), (i2), (k), (h'); repair (j)/(j2)

Phase B of the fonts round-2 design. Workflow only -- no patch, no rebuild.
Five changes to the #44 guard step:

(b2r) is the #83 discriminator. It is arm (b2) with one variable changed:
new_page() runs BEFORE add_init_script, so the only init-script invocation
lands on the document that is measured, in the process that renders it. If
the leak disappears, the list is process-local (sFontLists,
dom/base/FontListManager.cpp:14) while the disable flag is cross-process
(RoverfoxStorageManager, FontListManager.cpp:79-81) and a context can render
in a process that never received its list. If it survives, ordering is
irrelevant and the cause lies elsewhere. The arm refuses to score unless the
data-fl attribute proves setFontList ran on the document it measured: without
that, a context with no list is allowed everything and a broken setup prints
identically to a refuted hypothesis.

(j) and (j2) could not go red for the bug they guard. Both scored `final !=
tofu` where tofu was named['Arial'] -- and both values route through U+FFFD
system fallback, so during a real leak the cache answered both identically.
They now score by positive identification: the donor's list is exactly
["Tahoma"] (Verdana and Segoe UI collide at 44.533 and cannot be told apart),
the launch sets gfx.font_rendering.fallback.async=false so GlobalFontFallback
cannot take the StartCmapLoadingFromFamily skip at
gfx/thebes/gfxPlatformFontList.cpp:1581-1587, the donor's own automatic
fallback must land on Tahoma before the recipient is scored, and the tab
process ids are asserted equal rather than assumed -- #83's own process table
showed dom.ipc.processCount=1 does not collapse them, and
mReplacementCharFallbackFamily is a per-process singleton.

(i2) is arm (i) with both installs moved ahead of both renders. Arm (i) covers
install, render, install, render, where B's install runs
ClearCodepointsWithNoFonts() after A's miss was written -- the one sequence the
#81 fix handles. A caller that sets up its contexts before navigating spends
both clears first, and nothing clears the cache between A's render and B's, so
B reads tofu for a codepoint its own list covers. It scores against A's own
settled width, never against B's generics: FONTS['win'] covers CJK broadly, so
B's own refs legitimately reach the same real face B's gate finds, and arm (i)
hit exactly that false AssertionError on its first real run.

(k) measures #80's render half, which its recorded numbers never established:
the probe width was 761.33 under both launches and only the monospace
reference moved, and the probe font was a bundled family, so reference and
measurement could be the same typeface. The new probe is built at run time
with fontTools -- unitsPerEm 1000, glyph 'a' advancing 2000 -- so 20 glyphs at
48px measure exactly 1920 if and only if that face rendered. The bare launch
is the control: if it does not render there, where IsFontAllowed allows
everything, the payload is at fault and the arm says so.

(h') measures every family in bundle/fonts/macos in the mac context and prints
whichever matches 375.70001220703125, the width arm (h) has been unable to
attribute (#88). Diagnostic only; it scores nothing.

MN8 from PR #84's re-review: arm (h)'s control-clash check now includes the mac
context's own generics, not only the win context's.

Also hoists content_pids() above the arms that need it, adds tab_pids(), adds
fonttools to the step's pip install, and adds
.superpowers/sdd-fonts2/check_smoke_python.py, which byte-compiles every
embedded heredoc so a syntax error costs a second instead of a CI run. There
was no such check before.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round2
```

- [ ] **Step 9: Dispatch the Phase B smoke run and wait**

```bash
gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round2 -f run_id=34236331658
sleep 15
gh run list -R lang315/camoufox --workflow=smoke.yml --limit 3 \
  --json databaseId,headSha,status,createdAt \
  --jq '.[] | "\(.databaseId) \(.status) \(.headSha[0:7]) \(.createdAt)"'
```
Record the newest id as `<SMOKE_B>` in `.superpowers/sdd-fonts2/progress.md`.

To wait, load the Monitor tool once (`ToolSearch` with query
`select:Monitor`) and give it an until-loop on:
```bash
gh run view <SMOKE_B> -R lang315/camoufox --json status,conclusion \
  --jq '.status + " " + (.conclusion // "-")'
```
until the output starts with `completed`, with a 60-minute cap; re-arm once if it expires.
If Monitor is unavailable, poll the same command every three minutes. Expected end state:
`completed success` (~15 min). `completed failure` is still readable and Step 10 still runs —
read the log either way.

- [ ] **Step 10: Read every arm and write the gate**

```bash
gh run view <SMOKE_B> -R lang315/camoufox --log > .superpowers/sdd-fonts2/smoke-phaseB-<SMOKE_B>.log
grep -v '36;1m' .superpowers/sdd-fonts2/smoke-phaseB-<SMOKE_B>.log \
  | grep -E '\((b|b2|b2r|e|f|g|h|i|j|j2|k)\) |arm h. / #88|arm j . #82|arm j2 . #82|\[b2r|tripwire triage|RED \(expected\)|UNEXPECTED RED' \
  | sed -E 's/^[^Z]*Z//' | cut -c1-260 \
  | tee .superpowers/sdd-fonts2/smoke-phaseB-arms.txt
```

Expected before any fix, on this binary:

| Arm | Expected | What it means |
|---|---|---|
| `(b2)` | RED | #83 unfixed; unchanged from run 34240575679 |
| `(b2r)` | **GREEN if H1, RED if H1 refuted** | the gate |
| `(j)` | RED with context B settling at the donor's Tahoma width, or `unmeasured: different processes` | #82 unfixed |
| `(j2)` | RED with B settling at the bare donor's width, or `unmeasured: different processes` | #82 unfixed |
| `(i2)` | RED — context B settles at A's tofu floor | #81's ordering case, unfixed |
| `(k)` | RED on the status half — `error` under the list, `loaded` under the bare launch. The width under the list may be 1920 **or** a fallback; record which. | #80 unfixed |
| `(b)`, `(e)`, `(f)`, `(g)`, `(h)`, `(i)` | GREEN | unchanged from run 34240575679 |
| `(i2)` | RED — B renders tofu for a codepoint its own list covers | #81's ordering case |
| `arm h' / #88` | one family name, or `NO MATCH` | #88's answer |

Do **not** treat a pre-fix `(k)` width of 1920 as a broken arm. Recon A.1 leaves the render
half of #80 genuinely undetermined, and the more economical reading of #80's own numbers is
that the face rendered under both launches and only the reported status was wrong. The arm's
verdict handles both; the table records which one this build shows.

Then write the gate file. It must contain exactly one of the two verdict lines, because
Task 5 branches on that string and nothing else:

```bash
cat > .superpowers/sdd-fonts2/gate.md <<'EOF'
# Phase B gate — #83 hypothesis H1

Run: <SMOKE_B> (smoke.yml @ <workflow sha>, linux binary from build 34236331658 @ 8990915)

GATE: H1 CONFIRMED
# ^ exactly one of: "GATE: H1 CONFIRMED" | "GATE: H1 REFUTED"

## Lines this was read from
<paste the (b2), (b2r) and [b2r / ...] lines verbatim from smoke-phaseB-arms.txt>

## Reading rule applied
(b2) RED and (b2r) GREEN            -> H1 CONFIRMED  -> Task 5 carries the #83 fix.
(b2) RED and (b2r) RED with a leak  -> H1 REFUTED    -> Task 5 carries the MOZ_LOG line.
(b2r) RED with "setup invalid"      -> NEITHER. The arm did not measure. Fix the arm and
                                       re-dispatch Step 9 before Task 5 starts.
(b2) GREEN                          -> NEITHER. #83 no longer reproduces on this binary;
                                       stop and report, because the premise of Task 5 is gone.

## #88 (arm h'), recorded here so Task 9's PR body does not re-derive it
<paste the "[arm h' / #88] ANSWER:" line>

## #82 (arms j / j2), for the Task 7 before/after comparison
<paste the leak signature, B's settled width, B's floor, and the tab pids for both arms>
EOF
```

Append to the ledger: the run id, its conclusion, the gate line, and the `(k)` and `arm h'`
answers. Every number quoted here must be copied from `smoke-phaseB-arms.txt`, not recalled.

---

### Task 3: #80 — `url()` faces skip the family gate (`patches/font-hijacker.patch`)

One new member function on `FontFaceImpl` and three call-site edits. No gfx code. The
`local()` refusal in `gfx/thebes/gfxUserFontSet.cpp:456-470` is deliberately untouched, so a
mixed `src: local(X), url(Y)` rule still cannot reach a host font.

**Task 3 must be committed before Task 4 starts.** `font-hijacker.patch` sorts before
`font-list-spoofing.patch` by basename, so Task 4's `first-checkpoint` includes Task 3's
edited patch. Running them in parallel produces a `first-checkpoint` that does not match the
committed stack.

**Files:**
- Create: `.superpowers/sdd-fonts2/apply_upto_fh.py` (untracked)
- Modify: `patches/font-hijacker.patch`
- Modify (transiently, never committed): `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.h`,
  `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.cpp`,
  `camoufox-152.0.4-beta.31/layout/style/FontFace.cpp`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `bool FontFaceImpl::CamouHasNonLocalSource() const;` — public, no arguments,
  returns true for any `url()` source or an ArrayBuffer face. Tasks 4, 5 and 9 refer to it by
  that exact name.

- [ ] **Step 1: Make an `apply_upto` variant that stops before `font-hijacker.patch`**

`.superpowers/sdd-44/apply_upto.py` hardcodes `TARGET = "font-list-spoofing.patch"` (line 12).
Copy it with the target changed:

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
sed 's/^TARGET = .*/TARGET = "font-hijacker.patch"/' .superpowers/sdd-44/apply_upto.py \
  > .superpowers/sdd-fonts2/apply_upto_fh.py
grep -n '^TARGET' .superpowers/sdd-fonts2/apply_upto_fh.py
```
Expected: `12:TARGET = "font-hijacker.patch"`.

- [ ] **Step 2: Build the workspace**

```bash
python3 .superpowers/sdd-fonts2/apply_upto_fh.py 2>&1 | tail -25
```
Expected: `OK: all N pre-target patches applied clean`, then the target's own apply output,
then `=== .rej files left: []` and a `git status --short` listing the files
`font-hijacker.patch` touches. If any `.rej` is listed, stop: the patch does not apply to a
pristine tree and that is a separate problem from this task.

Confirm the checkpoint and the anchors you are about to edit:
```bash
cd camoufox-152.0.4-beta.31
git tag --points-at HEAD
grep -n 'nsAtom\* GetFamilyName() const;' layout/style/FontFaceImpl.h
grep -n 'IsFontAllowed(fontFamily)' layout/style/FontFace.cpp layout/style/FontFaceImpl.cpp
grep -n 'nsAtom\* FontFaceImpl::GetFamilyName() const' layout/style/FontFaceImpl.cpp
cd ..
```
Expected: `first-checkpoint`; `FontFaceImpl.h:142`; `FontFace.cpp:281`, `FontFace.cpp:308`,
`FontFaceImpl.cpp:365`; `FontFaceImpl.cpp:714`. If any line number differs, use the one the
grep prints — the anchors below are text, not numbers.

- [ ] **Step 3: Declare the member in `FontFaceImpl.h`**

In `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.h`, immediately after
`nsAtom* GetFamilyName() const;` (`:142`) and before the `/**` that begins "Returns whether
this object is CSS-connected", insert:

```cpp

  /**
   * Camoufox (#80): true when this face's bytes come from the page rather than
   * from a host-installed font -- any url() source, or an ArrayBuffer face.
   *
   * Read from the descriptor block, NOT from mUserFontEntry. On the JS
   * `new FontFace(...)` path the entry stays null until the face is added to a
   * set (FontFaceSetImpl::InsertNonRuleFontFace), so an mUserFontEntry-based
   * test would answer false in exactly the case a page most often uses --
   * `f.load()` and `f.status` read before `document.fonts.add(f)`.
   */
  bool CamouHasNonLocalSource() const;
```

- [ ] **Step 4: Define it in `FontFaceImpl.cpp`**

In `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.cpp`, immediately before
`nsAtom* FontFaceImpl::GetFamilyName() const {` (`:714`) — i.e. directly after
`GetAttributesFromRule`'s closing brace, where `Servo_FontFaceRule_GetSources` is already in
scope and already used at `:705` — insert:

```cpp
bool FontFaceImpl::CamouHasNonLocalSource() const {
  // An ArrayBuffer face has no `src` descriptor at all, so the URL scan below
  // would answer false for bytes the page supplied directly. mSourceType is
  // private, which is one reason this is a member and not a free helper.
  if (mSourceType == eSourceType_Buffer) {
    return true;
  }
  StyleLockedFontFaceRule* data = GetData();
  if (!data) {
    return false;  // cannot tell -> keep the gate
  }
  AutoTArray<StyleFontFaceSourceListComponent, 8> sources;
  Servo_FontFaceRule_GetSources(data, &sources);
  for (const auto& s : sources) {
    // IsUrl(), not !IsLocal(). The list is flat and interleaves
    // FormatHintKeyword, FormatHintString and TechFlags components
    // (servo/components/style/font_face.rs:227-236), so !IsLocal() would
    // count a format hint as a URL source.
    if (s.IsUrl()) {
      return true;
    }
  }
  return false;
}

```

`GetData()` is public and returns `StyleLockedFontFaceRule*` (`FontFaceImpl.h:233-236`), and
every one of the three call sites below already dereferences it indirectly through
`GetFamilyName()`, so no new lifetime assumption is introduced.

If the CI build fails on `s.IsUrl()`, the generated predicate is named differently for this
enum; the fallback is `s.tag == StyleFontFaceSourceListComponent::Tag::Url`. `IsUrl()` is used
on another cbindgen tagged enum in this same tree at
`layout/style/ServoStyleConstsInlines.h:1055`, and `IsLocal()` on this exact enum at
`layout/style/FontFaceSetDocumentImpl.cpp:544`, so the generated form is the expected one.

- [ ] **Step 5: Consult it at the three refusal sites**

Site 1 — `camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.cpp:365`, inside `SetStatus`.
Replace:
```cpp
  if (IsFontAllowed(fontFamily)) {
```
with:
```cpp
  // #80: a url() or ArrayBuffer face's family name is invented by the page and
  // can never be in an OS font list, so the family gate can only ever answer
  // "no" for it. Skip the gate for those; keep it for local()-only faces,
  // whose family name genuinely names a host font. Note this does NOT restore
  // real load status -- aStatus is still discarded here, tracked separately.
  if (CamouHasNonLocalSource() || IsFontAllowed(fontFamily)) {
```

Site 2 — `camoufox-152.0.4-beta.31/layout/style/FontFace.cpp:281`, inside `Status()`.
Replace:
```cpp
  if (mozilla::dom::IsFontAllowed(fontFamily)) {
```
with:
```cpp
  // #80: same skip as FontFaceImpl::SetStatus. This getter is the one a page
  // reads most often, and on the JS FontFace path it runs before the face has
  // a gfxUserFontEntry at all -- which is why the test is on the descriptor
  // block rather than the entry.
  if (mImpl->CamouHasNonLocalSource() || mozilla::dom::IsFontAllowed(fontFamily)) {
```

Site 3 — `camoufox-152.0.4-beta.31/layout/style/FontFace.cpp:308`, inside `Load()`.
Replace:
```cpp
  if (mozilla::dom::IsFontAllowed(fontFamily)) {
```
with:
```cpp
  // #80: same skip as Status() above, so `new FontFace(f, 'url(...)').load()`
  // resolves instead of rejecting for a family the page invented.
  if (mImpl->CamouHasNonLocalSource() || mozilla::dom::IsFontAllowed(fontFamily)) {
```

`mImpl` is already dereferenced at both `FontFace.cpp` sites, three lines above each, to build
`fontFamily`.

- [ ] **Step 6: Regenerate the patch**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts2/fh-new.patch
cd ..
```
`git add -A` here is inside the **source tree**, never the repo root, and the tree is a
throwaway git repo used only to produce this diff. `git reset -q _READY` mirrors what
`apply_upto.py` does at checkpoint time so the marker file never lands in the diff.

Confirm only the three intended files moved, and that no other section of the patch changed:
```bash
grep -c '^diff --git' patches/font-hijacker.patch .superpowers/sdd-fonts2/fh-new.patch
diff <(grep '^diff --git' patches/font-hijacker.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts2/fh-new.patch)
diff <(sed -n '/^diff --git a\/gfx\/thebes\/gfxUserFontSet.cpp/,/^diff --git a\/layout/p' patches/font-hijacker.patch) \
     <(sed -n '/^diff --git a\/gfx\/thebes\/gfxUserFontSet.cpp/,/^diff --git a\/layout/p' .superpowers/sdd-fonts2/fh-new.patch)
```
Expected: the two `diff --git` counts are equal and the file lists are identical (this change
adds no new file to the patch); the `gfxUserFontSet.cpp` section is byte-identical, proving
site 4 was not touched. If the section list gained or lost an entry, stop.

```bash
cp .superpowers/sdd-fonts2/fh-new.patch patches/font-hijacker.patch
```

- [ ] **Step 7: Dry-run with the applier the build actually uses**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-fonts2/apply_upto_fh.py >/dev/null 2>&1
cd camoufox-152.0.4-beta.31
git reset --hard first-checkpoint -q && git clean -fdq
/opt/homebrew/bin/gpatch -p1 --forward -l --binary --dry-run < ../patches/font-hijacker.patch
cd ..
```
Expected: `checking file ...` for each of the patch's files and **no** `Hunk #N FAILED`,
**no** `with fuzz`, and **no** `offset` on any `layout/style/` file.
`git apply --check` is not a valid substitute; do not use it.

Then read the applied tree back rather than trusting the exit status:
```bash
cd camoufox-152.0.4-beta.31
/opt/homebrew/bin/gpatch -p1 --forward -l --binary < ../patches/font-hijacker.patch >/dev/null
grep -n 'CamouHasNonLocalSource' layout/style/FontFaceImpl.h layout/style/FontFaceImpl.cpp layout/style/FontFace.cpp
cd ..
```
Expected exactly five hits: one declaration, one definition, and three call sites (one in
`FontFaceImpl.cpp` `SetStatus`, two in `FontFace.cpp`).

- [ ] **Step 8: Commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/font-hijacker.patch
git commit -m "fix(#80): url() web fonts skip the family-name gate

A page's own @font-face family name is invented by the page. It can never
appear in an OS font list, so the three family-name gates this patch adds --
FontFaceImpl::SetStatus, FontFace::Status() and FontFace::Load() -- can only
ever answer 'no' for a url() face. Under any launch carrying a fonts key, or
in any context that installed its own list, an ordinary web font is reported
'error' and FontFace.load() rejects. A browser that refuses web fonts is a
larger tell than the OS-name surface these gates exist to spoof.

FontFaceImpl::CamouHasNonLocalSource() reads the source list out of the Servo
descriptor block through GetData(), which every one of the three sites already
reaches indirectly via GetFamilyName(). It deliberately does NOT read
mUserFontEntry: on the JS FontFace path that entry is null until the face is
added to a set, so an entry-based test would keep the gate in exactly the shape
a page most often uses -- new FontFace(f, 'url(...)'), then .load() and .status
read before document.fonts.add(). The test is IsUrl(), not !IsLocal(), because
the source list is flat and interleaves format-hint and tech-flag components.
eSourceType_Buffer returns early: an ArrayBuffer face has no src descriptor at
all, so the URL scan alone would answer false for page-supplied bytes.

The local() refusal in gfx/thebes/gfxUserFontSet.cpp is untouched, so a mixed
src: local(X), url(Y) rule still cannot reach a host font. It will, however,
report 'loaded' for a family the context's list excludes; that is stated in the
PR, not fixed here.

Not fixed, and filed separately as #<FONTFACE_STATUS_ISSUE> (Task 1): SetStatus
still discards aStatus, so a url() face on an allowed family reports 'loaded'
even when the download genuinely fails.

Verified: gpatch -p1 --forward -l --binary dry-run clean on a first-checkpoint
tree, no fuzz and no offset on any layout/style file; five CamouHasNonLocalSource
occurrences in the applied tree (declaration, definition, three call sites);
the gfxUserFontSet.cpp section of the patch is byte-identical to before.
Measured by smoke arm (k), added in the previous commit.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: the commit sha, the five-hit grep result, and the dry-run outcome.

---

### Task 4: #82 and the #81 generalisation — read-path gating (`patches/font-list-spoofing.patch`)

Three edits in `gfx/thebes/gfxPlatformFontList.cpp` and one in `gfx/thebes/gfxTextRun.cpp`,
all inside `patches/font-list-spoofing.patch`, which already carries sections for both files.

**Files:**
- Modify: `patches/font-list-spoofing.patch`
- Modify (transiently, never committed):
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`,
  `camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp`

**Interfaces:**
- Consumes: Task 3's committed `patches/font-hijacker.patch` (it sorts first, so it is part
  of this task's `first-checkpoint`).
- Produces: no new symbol. Task 5, if it runs the H1 branch, edits a different section of the
  same patch file (`dom/base/FontListManager.{h,cpp}`) and must start from Task 4's committed
  state.

- [ ] **Step 1: Build the workspace at `font-list-spoofing.patch`**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py 2>&1 | tail -25
```
`.superpowers/sdd-44/apply_upto.py` already targets `font-list-spoofing.patch` — use it
unchanged, not the `_fh` copy from Task 3.

Expected: `OK: all N pre-target patches applied clean`, `=== .rej files left: []`. Confirm
Task 3's work is in this tree, since it applies before the target:
```bash
grep -c 'CamouHasNonLocalSource' camoufox-152.0.4-beta.31/layout/style/FontFaceImpl.cpp
```
Expected: `2` (definition plus the `SetStatus` call site). If it is `0`, Task 3 was not
committed and this task must not proceed.

- [ ] **Step 2: Gate the cached U+FFFD family**

In `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`, inside
`SystemFindFontForChar`'s `if (aCh == 0xFFFD) {` block (`:1328`), insert between the closing
brace of the `else if (fallbackFamily.mUnshared)` branch and the comment
`// this should never fail, as we must have found U+FFFD ...`:

```cpp
    // Camoufox (#82): mReplacementCharFallbackFamily is a member of
    // gfxPlatformFontList -- a per-process singleton -- and is keyed only by
    // FontVisibility, so the family an earlier context resolved is handed back
    // here to every later context at the same level with no per-context check
    // at all. Ask the same gate the slow path asks (:1577 shared, :1616
    // unshared) and, on refusal, fall through to CommonFontFallback /
    // GlobalFontFallback, both of which are gated. The cache is kept, not
    // cleared: the context that owns the entry keeps its fast path, and the
    // whole point of the optimisation survives.
    //
    // GetCurrentContext() is valid here. SystemFindFontForChar is reached from
    // gfxFontGroup::FindFontForChar via WhichSystemFontSupportsChar, which
    // opens AutoFontListContext(mUserContextId) at gfxTextRun.cpp:3956.
    //
    // Inherits the context-0 fail-open (CLAUDE.md lesson 5): with no context id
    // the cached family is returned unchecked, exactly as before.
    if (fontEntry) {
      nsAutoCString camouKey;
      if (fallbackFamily.mShared) {
        camouKey = fallbackFamily.mShared->Key().AsString(SharedFontList());
        GenerateFontListKey(camouKey);
      } else if (fallbackFamily.mUnshared) {
        GenerateFontListKey(fallbackFamily.mUnshared->Name(), camouKey);
      }
      if (!camouKey.IsEmpty() && !CamouIsFontAllowed(camouKey)) {
        fontEntry = nullptr;
      }
    }

```

The existing `if (fontEntry && fontEntry->HasCharacter(aCh))` return is left exactly as it is
and now falls through when `fontEntry` was nulled.

- [ ] **Step 3: Stop a context with its own list from honouring, or writing, the negative cache**

Edit 3a — `camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp:3493-3495`, inside
`gfxFontGroup::FindFontForChar`. Replace:
```cpp
  auto* pfl = gfxPlatformFontList::PlatformFontList();
  if (pfl->SkipFontFallbackForChar(level, aCh) ||
      (!StaticPrefs::gfx_font_rendering_fallback_unassigned_chars() &&
       GetGeneralCategory(aCh) == HB_UNICODE_GENERAL_CATEGORY_UNASSIGNED)) {
```
with:
```cpp
  auto* pfl = gfxPlatformFontList::PlatformFontList();
  // Camoufox (#82/#81): mCodepointsWithNoFonts is process-wide and keyed only
  // by FontVisibility, so one context's genuine, correctly gated miss answers
  // for every later context at the same level -- and a hit short-circuits
  // FindFontForChar before the per-context gate at WhichSystemFontSupportsChar
  // ever runs. A context that installed its own list has its own font universe
  // and must re-ask. Contexts without a list keep the upstream fast path, so
  // the optimisation is not lost, only narrowed.
  //
  // #81's clear-on-install (FontListManager::SetFontList ->
  // ClearCodepointsWithNoFonts) is kept and is not what makes this correct: it
  // fires when a context INSTALLS, and the failure fires when a context READS,
  // so a caller that installs both lists before either renders is unprotected
  // by it. This read-path check has no such ordering dependency.
  //
  // mUserContextId is this font group's own cached id (:1855-1875), not the
  // thread-local, so this does not depend on a scope being open at this line.
  const bool camouHasOwnList =
      mUserContextId != 0 &&
      mozilla::dom::FontListManager::HasFontList(mUserContextId);
  if ((!camouHasOwnList && pfl->SkipFontFallbackForChar(level, aCh)) ||
      (!StaticPrefs::gfx_font_rendering_fallback_unassigned_chars() &&
       GetGeneralCategory(aCh) == HB_UNICODE_GENERAL_CATEGORY_UNASSIGNED)) {
```
`gfxTextRun.cpp` already includes `mozilla/dom/FontListManager.h` at `:37`, and
`mUserContextId` is a `gfxFontGroup` member (`gfxTextRun.h:1409`), so no include changes.

Edit 3b — `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp:1401-1403`. Replace:
```cpp
  // no match? add to set of non-matching codepoints
  if (!font) {
    mCodepointsWithNoFonts[level].set(aCh);
  } else {
```
with:
```cpp
  // no match? add to set of non-matching codepoints
  if (!font) {
    // Camoufox (#82/#81): do not poison the process-wide negative cache from a
    // context that has its own list. The miss is a property of THAT context's
    // font universe, not of the process, and nothing ever clears this cache --
    // not even an async cmap load completing. Contexts without a list keep the
    // upstream behaviour.
    const uint32_t camouCtx = mozilla::dom::FontListManager::GetCurrentContext();
    if (camouCtx == 0 ||
        !mozilla::dom::FontListManager::HasFontList(camouCtx)) {
      mCodepointsWithNoFonts[level].set(aCh);
    }
  } else {
```

Edit 3c — the assertion at `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp:1320-1321`.
Edit 3a makes it legitimate for a list-carrying context to reach this function for a codepoint
already in the cache, which would trip the assert in a debug build. Replace:
```cpp
  MOZ_ASSERT(!mCodepointsWithNoFonts[level].test(aCh),
             "don't call for codepoints already known to be unsupported");
```
with:
```cpp
  // Camoufox (#82/#81): a context with its own font list deliberately bypasses
  // the process-wide negative cache in gfxFontGroup::FindFontForChar, so this
  // codepoint can legitimately be in the set when such a context asks.
  MOZ_ASSERT(!mCodepointsWithNoFonts[level].test(aCh) ||
                 (mozilla::dom::FontListManager::GetCurrentContext() != 0 &&
                  mozilla::dom::FontListManager::HasFontList(
                      mozilla::dom::FontListManager::GetCurrentContext())),
             "don't call for codepoints already known to be unsupported");
```

- [ ] **Step 4: Regenerate the patch**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts2/fls-new.patch
cd ..
diff <(grep '^diff --git' patches/font-list-spoofing.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts2/fls-new.patch)
for sec in dom/base/FontListManager.cpp dom/base/FontListManager.h \
           gfx/thebes/gfxPlatformFontList.h layout/style/FontFaceSet.cpp; do
  echo "--- $sec"
  diff <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' patches/font-list-spoofing.patch) \
       <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' .superpowers/sdd-fonts2/fls-new.patch)
done
```
Expected: identical section lists, and no output from any of the four per-section diffs — only
`gfxPlatformFontList.cpp` and `gfxTextRun.cpp` may change. If a section list entry appears or
disappears, stop.

```bash
cp .superpowers/sdd-fonts2/fls-new.patch patches/font-list-spoofing.patch
```

Regenerating through the workspace also removes the four fuzz-1 hunks #84 left behind, for
free. Confirm that happened rather than assuming it:
```bash
grep -c '^@@' patches/font-list-spoofing.patch
```
Record the number; it is quoted in Step 6's commit message and must be read back, not recalled.

- [ ] **Step 5: Dry-run, and confirm zero fuzz on `gfxPlatformFontList.cpp`**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py >/dev/null 2>&1
cd camoufox-152.0.4-beta.31
git reset --hard first-checkpoint -q && git clean -fdq
/opt/homebrew/bin/gpatch -p1 --forward -l --binary --dry-run \
  < ../patches/font-list-spoofing.patch 2>&1 | tee ../.superpowers/sdd-fonts2/fls-dryrun.log
grep -iE 'fuzz|offset|FAILED' ../.superpowers/sdd-fonts2/fls-dryrun.log
cd ..
```
The `git clean -fdq` after every `git reset --hard first-checkpoint` is not optional.
`font-list-spoofing.patch` **creates** `dom/base/FontListManager.{h,cpp}`, and `apply_upto.py`
commits `first-checkpoint` before applying the target, so a bare reset leaves those files
behind as untracked. The creation hunks then land on existing files, and `--forward` makes GNU
patch skip them without a word — the "clean" you would read is not what `make dir` sees.

Expected: no `FAILED`, and the fuzz/offset grep prints **nothing** — in particular nothing on
`gfxPlatformFontList.cpp`. `0 FAILED` alone is not a placement proof, so read the tree:
```bash
cd camoufox-152.0.4-beta.31
/opt/homebrew/bin/gpatch -p1 --forward -l --binary < ../patches/font-list-spoofing.patch >/dev/null
grep -n 'camouKey\|camouHasOwnList\|camouCtx' gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp
sed -n '/if (aCh == 0xFFFD) {/,/TimeStamp start/p' gfx/thebes/gfxPlatformFontList.cpp | tail -25
cd ..
```
Expected: the new gate sits **inside** the `aCh == 0xFFFD` block and **above** the
`if (fontEntry && fontEntry->HasCharacter(aCh))` return; `camouHasOwnList` appears once in
`gfxTextRun.cpp`; `camouCtx` once in `gfxPlatformFontList.cpp`.

- [ ] **Step 6: Commit**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/font-list-spoofing.patch
git commit -m "fix(#82 #81): gate the U+FFFD cache read and keep list-carrying contexts out of the negative cache

Two process-wide caches in gfxPlatformFontList are keyed only by
FontVisibility, with no relation to the user context id, and both are consulted
before any per-context gate runs.

mReplacementCharFallbackFamily (#82) is the positive one. Its read at
gfx/thebes/gfxPlatformFontList.cpp:1328-1348 returns a real, working font
handle an earlier context resolved, with no CamouIsFontAllowed check at all --
a genuine cross-context leak, not merely a coherence defect. The fix asks the
same gate the slow path asks, on the cached family's own key, and on refusal
falls through to CommonFontFallback / GlobalFontFallback, which are gated. The
cache is kept, so the context that owns the entry keeps its fast path.

mCodepointsWithNoFonts (#81) is the negative one, and this generalises the fix
that issue already carries. Clear-on-install fires when a context INSTALLS its
list; the failure fires when a context READS. A caller that creates both
contexts before either renders spends both clears first, and then context A's
gated miss is written after B's clear has already run. Nothing else ever clears
this cache -- not even an async cmap load completing. So the check belongs on
the read path: a context with its own list neither honours a hit in
gfxFontGroup::FindFontForChar nor records its own misses at
gfxPlatformFontList.cpp:1403. The clear-on-install is kept; it is harmless and
it covers the case where a context installs after an earlier miss.

The MOZ_ASSERT at the top of SystemFindFontForChar is widened for the same
reason: a list-carrying context can now legitimately reach it for a codepoint
already in the cache.

Both changes inherit CamouIsFontAllowed's context-0 fail-open (CLAUDE.md lesson
5). That is unchanged and stated in the PR, not fixed here.

Regenerating the patch through the workspace flow also dropped the four fuzz-1
hunks PR #84 left behind. Verified: gpatch dry-run has no FAILED and no fuzz or
offset line at all, and the applied tree shows the new gate inside the
aCh == 0xFFFD block above the HasCharacter return.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: the sha, the hunk count from Step 4, and the dry-run grep result.

---

### Task 5: #83 — cross-process list (branch A) or the `MOZ_LOG` discriminator (branch B)

Read `.superpowers/sdd-fonts2/gate.md` first. Run **branch A** if it says
`GATE: H1 CONFIRMED`, **branch B** if it says `GATE: H1 REFUTED`. If it says neither, or the
file does not exist, stop — Task 2 Step 10 did not finish.

```bash
grep -E '^GATE: H1 (CONFIRMED|REFUTED)$' .superpowers/sdd-fonts2/gate.md
```

**Files (branch A):**
- Modify: `patches/font-list-spoofing.patch`
- Modify (transiently): `camoufox-152.0.4-beta.31/dom/base/FontListManager.h`,
  `camoufox-152.0.4-beta.31/dom/base/FontListManager.cpp`

**Files (branch B):**
- Modify: `patches/font-list-spoofing.patch`
- Modify (transiently): `camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp`
- Modify: `.github/workflows/smoke.yml` (the `#44` step's `env:` block at `:2797`-`:2799`,
  the last `env:` in the file; the two earlier `LIBGL_ALWAYS_SOFTWARE` lines at `:360` and
  `:423` belong to other steps and must not be touched)

**Interfaces:**
- Consumes: Task 4's committed `patches/font-list-spoofing.patch`, and
  `.superpowers/sdd-fonts2/gate.md`.
- Produces (branch A): `FontListManager::FontListKeyForUserContext(uint32_t)`,
  `FontListManager::ParseAndStoreLocked(uint32_t, const nsAString&)` and
  `FontListManager::MaybeHydrateFontList(uint32_t)`, all private statics. The public surface
  (`SetFontList`, `HasFontList`, `IsFontAllowed`, `SetCurrentContext`, `GetCurrentContext`,
  `DisableFunction`, `IsFunctionEnabledForWebIDL`) is unchanged, so no caller moves.
- Produces (branch B): a `LOG_FONTLIST` line in `CamouIsFontAllowed`, and
  `MOZ_LOG: "fontlist:5"` in the smoke step's environment.

---

#### Branch A — `GATE: H1 CONFIRMED`

**A design refinement over the spec, and why.** The spec has `HasFontList` and `IsFontAllowed`
fall back to the cross-process string on a local miss. They cannot: `CamouIsFontAllowed` runs
on worker threads as well as the main thread and Servo style threads, and
`RoverfoxStorageManager::GetString` reaches `Preferences::GetCString` →
`Internals::GetPrefValue` → `Preferences::InitStaticMembers()`, which asserts
`NS_IsMainThread() || ServoStyleSet::IsInServoTraversal()`
(`modules/libpref/Preferences.cpp:3986-3987`). A fallback read inside those two functions
would assert on a worker in a debug build and is undefined at best in a release one.

So the cross-process copy is **written** by `SetFontList` exactly as the spec says, and
**hydrated** at the one main-thread site that is guaranteed to run in the rendering process
before it paints: `IsFunctionEnabledForWebIDL`. That function is the WebIDL `[Func]` gate for
`window.setFontList` (`dom/webidl/Window.webidl:950-953`), so it runs on the window's own main
thread, and the fork's init script performs `typeof window.setFontList` on every navigation,
which is what triggers it. Reaching it with `disabled == true` and no local list is the exact
signature of "another process installed this context's list and this one never received it".
`HasFontList` and `IsFontAllowed` keep reading only `sFontLists`, so nothing changes for any
off-main-thread caller.

- [ ] **A1: Build the workspace**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py 2>&1 | tail -20
grep -n 'camouHasOwnList' camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp
```
Expected: `.rej files left: []`, and one `camouHasOwnList` hit proving Task 4's commit is in
this tree.

- [ ] **A2: Declare the three private statics in `FontListManager.h`**

In `camoufox-152.0.4-beta.31/dom/base/FontListManager.h`, replace:
```cpp
 private:
  static nsString DisabledKeyForUserContext(uint32_t aId);
};
```
with:
```cpp
 private:
  static nsString DisabledKeyForUserContext(uint32_t aId);
  // #83: the key the raw, comma-separated list is stored under in
  // RoverfoxStorageManager (cross-process), alongside the process-local
  // parsed copy in sFontLists.
  static nsString FontListKeyForUserContext(uint32_t aId);
  // Parses a comma-separated list into sFontLists under sFontListMutex.
  // Takes that mutex and nothing else.
  static void ParseAndStoreLocked(uint32_t aUserContextId,
                                  const nsAString& aFontList);
  // #83: main thread only. Reads the cross-process copy and parses it into
  // sFontLists when this process has no local list for the context.
  static void MaybeHydrateFontList(uint32_t aUserContextId);
};
```

- [ ] **A3: Split the parse out of `SetFontList` and write the cross-process copy**

In `camoufox-152.0.4-beta.31/dom/base/FontListManager.cpp`, replace the whole of
`SetFontList` (`:23`-`:56`) with:

```cpp
nsString FontListManager::FontListKeyForUserContext(uint32_t aId) {
  nsAutoString key;
  key.AppendPrintf("fontlist_v_%u", aId);
  return key;
}

void FontListManager::ParseAndStoreLocked(uint32_t aId,
                                          const nsAString& aFontList) {
  nsTHashSet<nsCString> fontSet;
  nsAutoString remaining(aFontList);
  while (!remaining.IsEmpty()) {
    int32_t commaPos = remaining.FindChar(',');
    nsAutoString fontName;
    if (commaPos >= 0) {
      fontName = Substring(remaining, 0, commaPos);
      remaining.Cut(0, commaPos + 1);
    } else {
      fontName = remaining;
      remaining.Truncate();
    }
    fontName.Trim(" \t");
    if (fontName.IsEmpty()) continue;
    nsAutoCString utf8;
    CopyUTF16toUTF8(fontName, utf8);
    ToLowerCase(utf8);
    fontSet.Insert(utf8);
  }
  MutexAutoLock lock(sFontListMutex);
  sFontLists.InsertOrUpdate(aId, std::move(fontSet));
}

void FontListManager::SetFontList(uint32_t aId, const nsAString& aFontList) {
  ParseAndStoreLocked(aId, aFontList);

  // #83: the parsed set above lives in sFontLists, which is a process-local
  // static, while DisableFunction() writes its one-shot flag through
  // RoverfoxStorageManager, which is cross-process. A context whose
  // about:blank lands in one content process and whose real document lands in
  // another therefore installs its list in the first process and renders in
  // the second, where the setter is already disabled, sFontLists is empty for
  // this id, and CamouIsFontAllowed returns true for every family. Store the
  // raw list cross-process too -- the same shape WebGLParamsManager::SetVendor
  // uses (dom/base/WebGLParamsManager.cpp:23-27) -- so the rendering process
  // can hydrate from it. Deliberately outside sFontListMutex: PutString may do
  // IPC.
  RoverfoxStorageManager::PutString(FontListKeyForUserContext(aId), aFontList);

  // #81: a context installing its own font list invalidates the
  // process-wide "no font covers this codepoint" cache -- a codepoint
  // this context's own list can now serve must not still be answered
  // by an earlier context's stale miss. Deliberately outside
  // sFontListMutex: ClearCodepointsWithNoFonts() takes
  // gfxPlatformFontList::mLock, and every gated read path acquires mLock
  // before sFontListMutex, so holding both here in the other order would
  // be a lock-order inversion.
  gfxPlatformFontList::PlatformFontList()->ClearCodepointsWithNoFonts();
}
```

- [ ] **A4: Hydrate in `IsFunctionEnabledForWebIDL`**

In the same file, replace the body of `IsFunctionEnabledForWebIDL` from
`bool disabled = false;` to `return !disabled;` with:

```cpp
  bool disabled = false;
  RoverfoxStorageManager::GetBool(DisabledKeyForUserContext(id), disabled);
  // #83: `disabled` is cross-process; the list is not. Arriving here with
  // disabled == true and no local list means another process installed this
  // context's list and this one -- the one that is about to render -- never
  // received it. Hydrate from the cross-process copy now.
  if (disabled) {
    MaybeHydrateFontList(id);
  }
  return !disabled;
}

void FontListManager::MaybeHydrateFontList(uint32_t aId) {
  // Main thread only, and this is the only place the cross-process copy is
  // read. RoverfoxStorageManager::GetString reaches Preferences::GetCString ->
  // Preferences::InitStaticMembers(), which asserts
  // NS_IsMainThread() || ServoStyleSet::IsInServoTraversal()
  // (modules/libpref/Preferences.cpp:3986-3987), while CamouIsFontAllowed also
  // runs on worker threads -- so HasFontList()/IsFontAllowed() must NOT read it
  // themselves. A WebIDL [Func] gate runs on its window's main thread, and the
  // fork's own init script evaluates `typeof window.setFontList` on every
  // navigation, so every rendering process reaches this before it paints.
  MOZ_ASSERT(NS_IsMainThread());
  if (aId == 0 || HasFontList(aId)) {
    return;
  }
  nsAutoString stored;
  if (!RoverfoxStorageManager::GetString(FontListKeyForUserContext(aId),
                                         stored) ||
      stored.IsEmpty()) {
    return;
  }
  // Lock order: the cross-process read above happens with NO lock held, and
  // ParseAndStoreLocked takes sFontListMutex and nothing else. This path never
  // touches gfxPlatformFontList::mLock, so it cannot invert the
  // mLock -> sFontListMutex order every gated read path uses. Two threads
  // racing here would both parse the same string and InsertOrUpdate the same
  // value, which is harmless.
  //
  // Deliberately does NOT call ClearCodepointsWithNoFonts(): that takes mLock,
  // and hydration is not an install. The negative cache is handled on the read
  // path instead (see the #82 change in gfxFontGroup::FindFontForChar), which
  // is why that fix is read-path shaped and does not depend on the clear.
  ParseAndStoreLocked(aId, stored);
}
```

Add `#include "nsThreadUtils.h"` to the include block at the top of `FontListManager.cpp`
(for `NS_IsMainThread`), keeping the existing alphabetical-ish order:
```cpp
#include "gfxPlatformFontList.h"
#include "mozilla/Mutex.h"
#include "mozilla/dom/BrowsingContext.h"
#include "nsGlobalWindowInner.h"
#include "nsThreadUtils.h"
#include "xpcpublic.h"
```
`RoverfoxStorageManager.h` is already pulled in by `FontListManager.h:9`.

- [ ] **A5: Regenerate, dry-run, read the tree back**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts2/fls-83.patch
cd ..
diff <(grep '^diff --git' patches/font-list-spoofing.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts2/fls-83.patch)
for sec in gfx/thebes/gfxPlatformFontList.cpp gfx/thebes/gfxTextRun.cpp \
           gfx/thebes/gfxPlatformFontList.h layout/style/FontFaceSet.cpp; do
  echo "--- $sec"
  diff <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' patches/font-list-spoofing.patch) \
       <(awk -v s="diff --git a/$sec" '$0==s{f=1} f&&/^diff --git/&&$0!=s{exit} f' .superpowers/sdd-fonts2/fls-83.patch)
done
cp .superpowers/sdd-fonts2/fls-83.patch patches/font-list-spoofing.patch
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py >/dev/null 2>&1
cd camoufox-152.0.4-beta.31
git reset --hard first-checkpoint -q && git clean -fdq
/opt/homebrew/bin/gpatch -p1 --forward -l --binary --dry-run \
  < ../patches/font-list-spoofing.patch 2>&1 | grep -iE 'fuzz|offset|FAILED' || echo "clean"
/opt/homebrew/bin/gpatch -p1 --forward -l --binary < ../patches/font-list-spoofing.patch >/dev/null
grep -n 'FontListKeyForUserContext\|ParseAndStoreLocked\|MaybeHydrateFontList' \
  dom/base/FontListManager.h dom/base/FontListManager.cpp
cd ..
```
Expected: identical section lists; no output from the four per-section diffs (only
`FontListManager.h` and `FontListManager.cpp` may change); `clean`; and **11** grep hits —
3 declarations in the header, and 8 lines in the `.cpp`:

| Symbol | Definition | Call sites |
|---|---|---|
| `FontListKeyForUserContext` | 1 | 2 (`SetFontList`, `MaybeHydrateFontList`) |
| `ParseAndStoreLocked` | 1 | 2 (`SetFontList`, `MaybeHydrateFontList`) |
| `MaybeHydrateFontList` | 1 | 1 (`IsFunctionEnabledForWebIDL`) |

Count them. If `MaybeHydrateFontList` has one hit in the `.cpp` instead of two, A4's call site
did not land and the cross-process copy is written but never read.

- [ ] **A6: Commit (branch A)**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git add patches/font-list-spoofing.patch
git commit -m "fix(#83): store the per-context font list cross-process and hydrate the rendering process

Smoke run <SMOKE_B>, arm (b2r), confirmed hypothesis H1. Arm (b2) reproduces the
leak; arm (b2r) is the same two contexts with one variable changed --
new_page() before add_init_script, so the only init-script invocation lands on
the document that is measured -- and the leak disappears. The arm proved the
list was installed on that document by reading back the data-fl attribute
before scoring, so a context with no list cannot be mistaken for a fixed one.

The cause is the storage asymmetry between the value and the flag. The list
lives in `static nsTHashMap sFontLists` (dom/base/FontListManager.cpp:14),
process-local. The one-shot disable flag goes through RoverfoxStorageManager,
which is cross-process. A context whose about:blank lands in P1 and whose real
document lands in P2 installs its list in P1; P2 finds the setter already
disabled, never receives the list, and renders with HasFontList(ctx) false --
where CamouIsFontAllowed returns true for every family. Nothing was broken in
the gate; it had nothing to enforce.

SetFontList now also writes the raw list through
RoverfoxStorageManager::PutString, the same shape WebGLParamsManager::SetVendor
uses. A process that never ran SetFontList for an id hydrates from that copy.

The hydration point is IsFunctionEnabledForWebIDL, not HasFontList or
IsFontAllowed as first designed. Those two are called from CamouIsFontAllowed,
which runs on worker threads, and RoverfoxStorageManager::GetString reaches
Preferences::InitStaticMembers(), which asserts NS_IsMainThread() ||
IsInServoTraversal() (modules/libpref/Preferences.cpp:3986-3987). The WebIDL
[Func] gate runs on its window's own main thread, and the fork's init script
evaluates typeof window.setFontList on every navigation, so every rendering
process reaches it before it paints -- and reaching it with disabled true and
no local list is exactly the signature of the split. HasFontList and
IsFontAllowed still read only sFontLists, so no off-main-thread caller changes.

Lock order: the cross-process read happens with no lock held;
ParseAndStoreLocked takes sFontListMutex and nothing else; hydration never
touches gfxPlatformFontList::mLock. The mLock -> sFontListMutex order every
gated read path uses is preserved.

Consequence, stated rather than hidden: a hydrating process never runs #81's
clear-on-install. That is why the #82/#81 fix in the previous commit is
read-path shaped and does not depend on that clear.

Verified: gpatch dry-run clean with no fuzz or offset; the applied tree carries
all three new statics with their call sites.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

#### Branch B — `GATE: H1 REFUTED`

H1 is dead, so #83 is not fixed by this PR. Spend the same build on deciding H2
(`gfxFontGroup::mUserContextId == 0`) instead, and report #83 as measured-not-fixed.

- [ ] **B1: Build the workspace (identical to A1)**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py 2>&1 | tail -20
grep -n 'camouHasOwnList' camoufox-152.0.4-beta.31/gfx/thebes/gfxTextRun.cpp
```
Expected: `.rej files left: []`, one `camouHasOwnList` hit.

- [ ] **B2: Add the log line to `CamouIsFontAllowed`**

`gfx/thebes/gfxPlatformFontList.cpp` already defines `LOG_FONTLIST` at `:60`-`:61` as
`MOZ_LOG(gfxPlatform::GetLog(eGfxLog_fontlist), LogLevel::Debug, args)`. Use that macro —
do not add a new module. In
`camoufox-152.0.4-beta.31/gfx/thebes/gfxPlatformFontList.cpp:1232`-`:1239`, replace:

```cpp
static bool CamouIsFontAllowed(const nsACString& aLowerKey) {
  uint32_t ctx = mozilla::dom::FontListManager::GetCurrentContext();
  if (ctx != 0 && mozilla::dom::FontListManager::HasFontList(ctx)) {
    return mozilla::dom::FontListManager::IsFontAllowed(ctx, aLowerKey);
  }
  return true;
}
```
with:
```cpp
static bool CamouIsFontAllowed(const nsACString& aLowerKey) {
  uint32_t ctx = mozilla::dom::FontListManager::GetCurrentContext();
  bool hasList = ctx != 0 && mozilla::dom::FontListManager::HasFontList(ctx);
  // #83 discriminator. Smoke arm (b2r) refuted hypothesis H1 (the list being
  // installed in a process that does not render), so the remaining candidate is
  // H2: gfxFontGroup caches mUserContextId once in its constructor through four
  // hops that each fail silently to 0 (gfx/thebes/gfxTextRun.cpp:1855-1875),
  // and this gate treats 0 as "no per-context list" and allows everything.
  // ctx=0 names H2; a real ctx with hasList=0 names something new. Uses the
  // module this file already has and costs nothing when it is off; read with
  // MOZ_LOG=fontlist:5.
  LOG_FONTLIST(("CAMOU-GATE key=%s ctx=%u hasList=%d",
                nsPromiseFlatCString(aLowerKey).get(), ctx, hasList ? 1 : 0));
  if (hasList) {
    return mozilla::dom::FontListManager::IsFontAllowed(ctx, aLowerKey);
  }
  return true;
}
```

- [ ] **B3: Turn the module on in the smoke step**

In `.github/workflows/smoke.yml`, the `#44` step's `env:` block reads:
```yaml
        env:
          CAMOUFOX_BIN: ${{ steps.bin.outputs.bin }}
          LIBGL_ALWAYS_SOFTWARE: "1"
```
Replace it with:
```yaml
        env:
          CAMOUFOX_BIN: ${{ steps.bin.outputs.bin }}
          LIBGL_ALWAYS_SOFTWARE: "1"
          # #83: arm (b2r) refuted H1, so the remaining candidate is H2 --
          # gfxFontGroup caching a user context id of 0. CamouIsFontAllowed logs
          # ctx and hasList on this module; ctx=0 on the arm (b2) probes names
          # H2, a real ctx with hasList=0 names something not yet hypothesised.
          MOZ_LOG: "fontlist:5"
          MOZ_LOG_FILE: "/tmp/camou-fontlist"
          # CamouIsFontAllowed logs from CONTENT processes, and the Linux content
          # sandbox refuses the /tmp write, so without this the dump step below
          # prints "(no log written)" and the build is spent for nothing. The
          # PR #84 diagnostic step carried exactly this env for exactly this
          # reason.
          MOZ_DISABLE_CONTENT_SANDBOX: "1"
```
and add a step immediately after the `#44` step:
```yaml
      - name: "#83 discriminator: CamouIsFontAllowed gate log"
        if: always()
        run: |
          echo "=== CAMOU-GATE lines (deduplicated, with counts) ==="
          cat /tmp/camou-fontlist* 2>/dev/null | grep -o 'CAMOU-GATE key=[^ ]* ctx=[0-9]* hasList=[01]' \
            | sort | uniq -c | sort -rn | head -60 || echo "(no log written)"
          echo "=== distinct ctx values seen ==="
          cat /tmp/camou-fontlist* 2>/dev/null | grep -o 'ctx=[0-9]* hasList=[01]' \
            | sort | uniq -c || echo "(none)"
```

`MOZ_LOG=fontlist:5` selects level 5 (Verbose), which includes the Debug level
`LOG_FONTLIST` emits at.

- [ ] **B4: Regenerate, dry-run, check the workflow**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/camoufox-152.0.4-beta.31
git add -A
git reset -q _READY || true
git diff --cached first-checkpoint > ../.superpowers/sdd-fonts2/fls-83log.patch
cd ..
diff <(grep '^diff --git' patches/font-list-spoofing.patch) \
     <(grep '^diff --git' .superpowers/sdd-fonts2/fls-83log.patch)
cp .superpowers/sdd-fonts2/fls-83log.patch patches/font-list-spoofing.patch
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
python3 .superpowers/sdd-44/apply_upto.py >/dev/null 2>&1
cd camoufox-152.0.4-beta.31
git reset --hard first-checkpoint -q && git clean -fdq
/opt/homebrew/bin/gpatch -p1 --forward -l --binary --dry-run \
  < ../patches/font-list-spoofing.patch 2>&1 | grep -iE 'fuzz|offset|FAILED' || echo "clean"
cd ..
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml "$TMPDIR/smoke-py-83"
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml')); print('YAML OK')"
```
Expected: identical section lists; `clean`; all blocks `0 failed`; `YAML OK`.

- [ ] **B5: Commit (branch B)**

```bash
git add patches/font-list-spoofing.patch .github/workflows/smoke.yml
git commit -m "diag(#83): log the gate's context, since arm (b2r) refuted H1

Smoke run <SMOKE_B>, arm (b2r): moving new_page() before add_init_script, so
the only init-script invocation lands on the document that is measured, did NOT
remove the leak. The data-fl read-back proves the list was installed on that
document, so this is a refutation and not a broken setup. Hypothesis H1 -- the
list being process-local while the disable flag is cross-process, leaving the
rendering process with nothing to enforce -- is dead, and #83 is not fixed by
this PR.

CamouIsFontAllowed now logs the context id, whether that context has a list,
and the key it was asked about, through the LOG_FONTLIST macro the file already
defines (gfx/thebes/gfxPlatformFontList.cpp:60-61, module fontlist). It costs
nothing when the module is off. The smoke step runs with MOZ_LOG=fontlist:5 and
dumps the deduplicated lines, so the next candidate is decided by the same
build this PR already spends: ctx=0 on the arm (b2) probes names H2
(gfxFontGroup caching a user context id of 0 through four silently-failing hops
at gfx/thebes/gfxTextRun.cpp:1855-1875); a real ctx with hasList=0 names
something not yet hypothesised.

#83 stays open with no auto-close keyword, and the PR reports it as
measured-not-fixed.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Append to the ledger: which branch ran, the sha, and the dry-run result.

---

### Task 6: Integrate — full patch apply, three builds

**Files:**
- Modify: `.superpowers/sdd-fonts2/progress.md` (untracked)
- No tracked file changes. This task proves the committed stack applies and starts the builds.

**Interfaces:**
- Consumes: Tasks 3, 4 and 5, all committed.
- Produces: three build run ids recorded in `.superpowers/sdd-fonts2/progress.md` as
  `BUILD_LINUX=<id>`, `BUILD_WINDOWS=<id>`, `BUILD_MACOS=<id>`, all at the same head sha,
  recorded as `FIX_SHA=<sha>`. Task 7 uses the Linux and macOS ids, Task 8 the Windows one.

**Deviation from the spec, stated rather than absorbed.** The spec's Phase C dispatches two
builds, Linux and Windows. Phase D then requires `build-tester` headful with `DISPLAY=:0` and
`service-tester`, both of which run on the user's macOS machine against a
`Camoufox.app/Contents/MacOS/camoufox` binary, and the baseline they are compared against
(1061/1070) is a macOS arm64 number. A Linux ELF cannot serve that. This task therefore
dispatches a third build, `macos-arm64`, at the same sha and in parallel, so it costs queue
capacity and no wall-clock time.

- [ ] **Step 1: Apply the whole stack the way the build does**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git status --short
make revert
git -C camoufox-152.0.4-beta.31 clean -fdq
CAMOU_PATCH=/opt/homebrew/bin/gpatch make dir 2>&1 \
  | tee .superpowers/sdd-fonts2/make-dir-final.log | tail -20
grep -c 'FAILED' .superpowers/sdd-fonts2/make-dir-final.log
grep -niE 'fuzz|offset' .superpowers/sdd-fonts2/make-dir-final.log
```
Expected: a clean `git status --short` before starting; `0` FAILED; and the fuzz/offset grep
printing **only** the `window-setter-seal.patch` hunk on `dom/base/FontListManager.cpp`, whose
offset moves again because Task 5 branch A changed that file. That offset carries no fuzz and
is accepted; it goes in the PR body. Any fuzz or offset on `gfxPlatformFontList.cpp`,
`gfxTextRun.cpp`, `FontFaceImpl.cpp`, `FontFaceImpl.h` or `FontFace.cpp` is a stop.

`0 FAILED` is not a placement proof. Read the applied tree:
```bash
cd camoufox-152.0.4-beta.31
grep -n 'CamouHasNonLocalSource' layout/style/FontFaceImpl.h layout/style/FontFaceImpl.cpp layout/style/FontFace.cpp | wc -l
grep -n 'camouKey' gfx/thebes/gfxPlatformFontList.cpp
grep -n 'camouHasOwnList' gfx/thebes/gfxTextRun.cpp
grep -n 'MaybeHydrateFontList\|CAMOU-GATE' dom/base/FontListManager.cpp gfx/thebes/gfxPlatformFontList.cpp
cd ..
```
Expected: `5`; the `camouKey` block inside the `aCh == 0xFFFD` fast path; one
`camouHasOwnList`; and — depending on the gate — either `MaybeHydrateFontList` in
`FontListManager.cpp` (branch A) or `CAMOU-GATE` in `gfxPlatformFontList.cpp` (branch B), not
both.

- [ ] **Step 2: Record the sha and dispatch three builds**

```bash
git log --oneline -6
git rev-parse HEAD
git push origin fix/fonts-round2
gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round2 -f build_target=linux-x86_64
gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round2 -f build_target=windows-x86_64
gh workflow run build.yml -R lang315/camoufox --ref fix/fonts-round2 -f build_target=macos-arm64
sleep 20
gh run list -R lang315/camoufox --workflow=build.yml --limit 5 \
  --json databaseId,headSha,status,displayTitle,createdAt \
  --jq '.[] | "\(.databaseId) \(.status) \(.headSha[0:7]) \(.createdAt) \(.displayTitle)"'
```

`gh run list` does not report the `build_target` input, so map the three ids to their targets
by reading each run's own jobs rather than by guessing from order:
```bash
for id in <id1> <id2> <id3>; do
  echo -n "$id -> "
  gh run view "$id" -R lang315/camoufox --json jobs --jq '[.jobs[].name] | join(", ")'
done
```

Write all three into the ledger:
```bash
cat >> .superpowers/sdd-fonts2/progress.md <<EOF
FIX_SHA=$(git rev-parse HEAD)
BUILD_LINUX=<id>
BUILD_WINDOWS=<id>
BUILD_MACOS=<id>
Task 6: make dir 0 FAILED (.superpowers/sdd-fonts2/make-dir-final.log); only
window-setter-seal.patch's FontListManager.cpp hunk carries an offset, no fuzz.
EOF
```

- [ ] **Step 3: Wait for all three**

Load `Monitor` (`ToolSearch` with query `select:Monitor`) and give it an until-loop on:
```bash
for id in <BUILD_LINUX> <BUILD_WINDOWS> <BUILD_MACOS>; do
  echo -n "$id "; gh run view "$id" -R lang315/camoufox --json status,conclusion \
    --jq '.status + " " + (.conclusion // "-")'
done
```
until every line starts with `completed`, capped at 60 minutes, re-armed until all three land
(builds run 40–95 minutes, so expect two or three arming cycles). If Monitor is unavailable,
poll the same loop every five minutes.

Expected: three `completed success` lines. A `completed failure` on any leg means the patch
does not compile — read `gh run view <id> --log-failed`, fix in the owning task (3, 4 or 5),
and re-dispatch all three at the new sha so the PR's evidence is from one commit.

Record each conclusion in the ledger before moving on, read back from `gh`, not recalled.

---

### Task 7: Phase D — final smoke, build-tester, service-tester

**Files:**
- Modify: `.github/workflows/smoke.yml` (`EXPECTED_RED` only)
- Create: `.superpowers/sdd-fonts2/smoke-final-<id>.log`,
  `.superpowers/sdd-fonts2/smoke-final-arms.txt`,
  `.superpowers/sdd-fonts2/build-tester.{log,json}`,
  `.superpowers/sdd-fonts2/service-tester.log`,
  `.superpowers/sdd-fonts2/task7-evidence.md` (all untracked)

**Interfaces:**
- Consumes: `BUILD_LINUX`, `BUILD_MACOS`, `FIX_SHA` from Task 6; `.superpowers/sdd-fonts2/gate.md`.
- Produces: `.superpowers/sdd-fonts2/task7-evidence.md`, which Task 9's PR body quotes verbatim.

- [ ] **Step 1: Retire the fixed arms from `EXPECTED_RED`**

Replace the `EXPECTED_RED` dict with the set that is still expected red **after** the fixes.
Branch A (H1 confirmed) — nothing in this list is expected red any more:
```python
          EXPECTED_RED = {}
```
Branch B (H1 refuted) — #83 is measured, not fixed, so its two arms stay:
```python
          EXPECTED_RED = {
              "(b2)": "#83, cross-context font leak, donor-alive; measured this run "
                      "(MOZ_LOG=fontlist:5) but NOT fixed -- H1 refuted by arm (b2r)",
              "(b2r)": "#83, same, with the init script on the document under test",
          }
```
An empty dict is handled correctly by the triage loop: the `for k, why in EXPECTED_RED.items()`
loop prints nothing and `unexpected` collects every tripwire, which is what should happen.

Check and commit:
```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 .superpowers/sdd-fonts2/check_smoke_python.py .github/workflows/smoke.yml "$TMPDIR/smoke-py-d"
git add .github/workflows/smoke.yml
git commit -m "test: no arm is expected red any more (#80, #82, #83 fixed)

Arms (b2), (b2r), (j), (j2) and (k) all guard defects this branch closes, so an
entry left in EXPECTED_RED would hide a regression in the fix itself. The
triage block still reports any arm that goes red, and now reports every one of
them as UNEXPECTED.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin fix/fonts-round2
```
On branch B the commit message instead says which two arms stay and why.

- [ ] **Step 2: Final smoke on the Linux artifact**

```bash
gh workflow run smoke.yml -R lang315/camoufox --ref fix/fonts-round2 -f run_id=<BUILD_LINUX>
sleep 15
gh run list -R lang315/camoufox --workflow=smoke.yml --limit 3 \
  --json databaseId,status,createdAt --jq '.[] | "\(.databaseId) \(.status) \(.createdAt)"'
```
Record the id as `SMOKE_FINAL`. Wait with Monitor as in Task 2 Step 9 (~15 min), then:
```bash
gh run view <SMOKE_FINAL> -R lang315/camoufox --log \
  > .superpowers/sdd-fonts2/smoke-final-<SMOKE_FINAL>.log
grep -v '36;1m' .superpowers/sdd-fonts2/smoke-final-<SMOKE_FINAL>.log \
  | grep -E '\((b|b2|b2r|e|f|g|h|i|j|j2|k)\) |arm h. / #88|tripwire triage|RED \(expected\)|UNEXPECTED RED' \
  | sed -E 's/^[^Z]*Z//' | cut -c1-260 \
  | tee .superpowers/sdd-fonts2/smoke-final-arms.txt
gh run view <SMOKE_FINAL> -R lang315/camoufox --json jobs \
  --jq '.jobs[].steps[] | select(.conclusion != null) | "\(.conclusion)\t\(.name)"'
```

Expected arm table on branch A:

| Arm | Expected | Guards |
|---|---|---|
| `(b)` | GREEN | per-context narrowing, donor closed |
| `(b2)` | GREEN | #83, donor alive |
| `(b2r)` | GREEN | #83, init script on the document under test |
| `(e)` `(f)` `(g)` `(h)` `(i)` | GREEN | unchanged from run 34240575679 |
| `(j)` | GREEN — context B settles at its own floor, not the donor's Tahoma, with the tab pids equal | #82 |
| `(j2)` | GREEN — same shape, bare donor | #82 |
| `(k)` | GREEN — status `loaded` and width 1920 under **both** launches | #80 |
| triage | no `UNEXPECTED RED` line, and no `was expected red, so the defect it guards may be fixed` line | |

On branch B, `(b2)` and `(b2r)` are `RED (expected)`, the `#83 discriminator` step prints the
`ctx=` / `hasList=` histogram, and the PR reports #83 as measured-not-fixed with whichever
value that histogram names.

A `(j)` or `(j2)` line reading `unmeasured: different processes` is **not** a pass. It means
`fission.autostart=false` did not collapse the processes either, and #82's fix is unverified.
Record it as such; do not report #82 as fixed on an unmeasured arm.

- [ ] **Step 3: `build-tester` headful on the macOS artifact**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
gh api repos/lang315/camoufox/actions/runs/<BUILD_MACOS>/artifacts \
  --jq '.artifacts[] | "\(.id) \(.name) \(.size_in_bytes)"'
gh api repos/lang315/camoufox/actions/artifacts/<artifact id>/zip > /tmp/cfx-r2.zip
mkdir -p /tmp/cfx-r2 && unzip -q /tmp/cfx-r2.zip -d /tmp/cfx-r2
ls /tmp/cfx-r2
```
Unpack the inner archive until `/tmp/cfx-r2/cf/Camoufox.app/Contents/MacOS/camoufox` exists
(that is the layout PR #86 and PR #84 both used), then:
```bash
xattr -dr com.apple.quarantine /tmp/cfx-r2/cf/Camoufox.app
rm -f build-tester/scripts/checks-bundle.js
uv venv build-tester/.venv
uv pip install --python build-tester/.venv/bin/python -r build-tester/requirements.txt 'playwright==1.55.0'
build-tester/.venv/bin/python -m playwright install firefox
```
`checks-bundle.js` is untracked and is built once, so a stale copy drifts from
`build-tester/src/lib/checks/index.ts` and silently shrinks the denominator — that is what
produced 1064 instead of 1070 in PR #84. Deleting it makes `ensure_bundle` rebuild from
source. Read `build-tester/run_tests.sh` before running to confirm the venv path and the
bundle step still match this; if it now builds the bundle itself, let it.

```bash
cd build-tester && DISPLAY=:0 .venv/bin/python scripts/run_tests.py \
  --executable-path /tmp/cfx-r2/cf/Camoufox.app/Contents/MacOS/camoufox \
  --json ../.superpowers/sdd-fonts2/build-tester.json 2>&1 \
  | tee ../.superpowers/sdd-fonts2/build-tester.log | tail -25; cd ..
```
Expected: Grade A, denominator **1070** (equal to `main`'s after the bundle rebuild), and the
only failures the known ones — 8× `canvasPerturbation` marker and possibly 1×
`noSwiftShader` llvmpipe. A denominator of 1064 means the bundle did not rebuild. Any new
failing check under Font Platform or Font Environment is a stop: read it, do not average it
away. Headless is not an option here — `run_tests.sh` refuses without a display, and headless
Firefox scores five WebGL checks free while dropping twelve from the denominator.

- [ ] **Step 4: `service-tester` with the user-supplied proxy**

Ask the user to place a live proxy in `service-tester/proxies.txt` and confirm it is there;
that file is gitignored and must never be printed, quoted, committed, or included in any
report.

```bash
uv venv service-tester/.venv
uv pip install --python service-tester/.venv/bin/python -r service-tester/requirements.txt 'playwright==1.55.0'
cd service-tester && .venv/bin/python run_tests.py \
  --executable-path /tmp/cfx-r2/cf/Camoufox.app/Contents/MacOS/camoufox \
  --profile-count 3 --proxies proxies.txt 2>&1 \
  | tee ../.superpowers/sdd-fonts2/service-tester.log \
  | grep -vi 'proxy\|@' | tail -20; cd ..
```
Expected: Grade A with a non-zero denominator, ideally 384/384 as on the PR #84 candidate, and
no new failed checks. A score of `0/0` is a vacuous run, not a pass (that is #89) — report it
as not verified rather than as a grade. The `grep -vi 'proxy\|@'` filter keeps the host out of
the terminal; the full log on disk still contains it, so never `cat` it and never paste from
it.

- [ ] **Step 5: Write the evidence file**

Create `.superpowers/sdd-fonts2/task7-evidence.md` containing, every value read back from the
logs rather than recalled: `FIX_SHA`; the three build ids and their conclusions; `SMOKE_FINAL`
with the per-arm lines verbatim and the step-conclusion list; the `build-tester` grade,
denominator, and the classified list of failing checks; the `service-tester` grade and
denominator with no proxy detail; and the exact commands run. Append a one-line summary to the
ledger.

There is no commit in Steps 2 to 5 — every artefact is under `.superpowers/`.

---

### Task 8: Phase E — #87 native Windows probe

Runs on the user's Windows build PC against the Windows artifact from `BUILD_WINDOWS`. There
is no Windows runner anywhere in `.github/workflows/` (`smoke.yml:18` is `runs-on:
ubuntu-24.04` and is the only runner declaration in the file), and `build-tester/run_tests.sh`
has no Windows branch, so this is a standalone script run by hand. Nothing to extend.

**Files:**
- Create: `build-tester/scripts/probe_windows_fonts.py` (tracked)
- Create: `.superpowers/sdd-fonts2/probe-windows-<date>.json`, `.log` (untracked)

**Interfaces:**
- Consumes: `BUILD_WINDOWS` from Task 6.
- Produces: a JSON result object with the keys `host_family`, `bare`, `launch_list`,
  `per_context`, `env`, and `verdicts`. Task 9's PR body and the #87 comment quote it.

**A correction to the spec's expectation, derived from the code rather than assumed.** The
spec says the chosen host family should be "not reachable by content in either launch". Read
`gfx/thebes/gfxPlatformFontList.cpp:896-908`:

```cpp
bool gfxPlatformFontList::MaskedFontListAppliesTo(
    FontVisibilityProvider* aFontVisibilityProvider) {
  if (!MaskConfig::HasFontAllowlist()) {
    return false;
  }
  ...
  return aFontVisibilityProvider && !aFontVisibilityProvider->IsChrome();
}
```

With no `fonts` key there is no allowlist, so the launch-level mask does not apply and host
fonts **are** reachable under a bare launch. That is correct behaviour, not a leak — and it is
the arm's positive control: if the host family were unreachable in the bare launch too, the
probe would be measuring nothing and could not tell a working gate from a font that simply is
not installed. The three expectations the script actually asserts are:

| Launch | Host family outside the list | Meaning |
|---|---|---|
| bare (no `fonts` key, no `setFontList`) | **reachable** | positive control — the probe can see host fonts at all |
| `CAMOU_CONFIG` with a `fonts` key excluding it | **not reachable** | the lookup-time flip holds on Windows |
| bare launch plus a per-context `setFontList` excluding it | **not reachable** | `CamouIsFontAllowed` holds on Windows |

- [ ] **Step 1: Precondition — the user opens the SSH master**

Ask the user to open the SSH master session to the build PC (`buildpc`) themselves and to
confirm it is up. Password authentication is in play and repeated failures trip a lockout, so
**never** retry authentication automatically and never attempt a second connection after a
failure. Verify before doing anything else:

```bash
ssh -O check buildpc 2>&1
```
Expected: a line reporting the master process is running. Anything else means stop and ask
the user again; do not try to open it. Do not put the host address or port anywhere in this
repo — `buildpc` is the alias, and the connection details live in the user's SSH config.

- [ ] **Step 2: Check for a native Windows Python and Playwright**

WSL does not count. The question is about `C:\Windows\Fonts` on the Windows host, so the
interpreter must be the native one.

```bash
ssh buildpc 'py -3 --version; py -3 -c "import sys; print(sys.executable)"'
ssh buildpc 'py -3 -m pip show playwright 2>&1 | findstr /B "Name Version Location"'
ssh buildpc 'py -3 -m pip show fonttools 2>&1 | findstr /B "Name Version"'
```
Expected: Python 3.11 or newer, an executable path under `C:\`, `playwright 1.55.0`, and
`fonttools` present. `fonttools` is needed on the Windows side too, to read family names out
of `C:\Windows\Fonts`.

If anything is missing, create a venv on the large drive and install into it:
```bash
ssh buildpc 'py -3 -m venv D:\camoufox-probe-venv'
ssh buildpc 'D:\camoufox-probe-venv\Scripts\python.exe -m pip install --quiet "playwright==1.55.0" fonttools'
ssh buildpc 'D:\camoufox-probe-venv\Scripts\python.exe -m pip show playwright | findstr /B "Version"'
```
Expected: `Version: 1.55.0` exactly. A newer Playwright reports 0/0 against camoufox-152 and
looks like a clean pass.

- [ ] **Step 3: Write the probe script**

Create `build-tester/scripts/probe_windows_fonts.py`:

```python
#!/usr/bin/env python3
"""#87: run the #44 font guard's probes against a Windows Camoufox binary on a
native Windows host.

The smoke workflow is Linux-only (`.github/workflows/smoke.yml` runs on
ubuntu-24.04 and declares no other runner), so the question it cannot answer is
whether host-installed Windows fonts outside the launch list are still
unreachable by content after the lookup-time allowlist flip. Before the flip
`ApplyWhitelist()` physically deleted them; now they are filtered at lookup
time by MaskedFontListAppliesTo / MaskedFontListBlocks and, per context, by
CamouIsFontAllowed.

Usage:
  python probe_windows_fonts.py --executable-path "C:\\path\\to\\camoufox.exe" \
      [--json out.json] [--headful]

Exit status is 0 when every verdict passed, 1 otherwise.
"""
import argparse
import glob
import json
import os
import sys

from playwright.sync_api import sync_playwright

# Measured at 48px with an explicit monospace fallback, exactly as smoke arms
# (g) and (h) do, so a family that does NOT resolve reads as the monospace
# baseline rather than as zero.
JS_MEASURE = """(families) => {
  const c = document.createElement('canvas').getContext('2d');
  const s = 'mmmmmmmmmmlliWWWWWWW@#$%^&*()_+';
  const w = (f) => { c.font = '48px "' + f + '", monospace'; return c.measureText(s).width; };
  const out = {};
  // Two DIFFERENT impossible families. Both must fall back to the same face,
  // so equal widths. If they ever differ, width comparison has stopped meaning
  // "did this family resolve" and every verdict below is void.
  out['__absent1__'] = w('__CamouAbsentRef__0001');
  out['__absent2__'] = w('__NoSuchFamily__12345');
  for (const f of families) out[f] = w(f);
  // U+FFFD codepoint fallback, which the family-name arms do not exercise at
  // all: SystemFindFontForChar / GlobalFontFallback rather than
  // FindAndAddFamiliesLocked.
  c.font = '48px "__NoSuchFamilyAtAll6__"';
  out['__fffd__'] = c.measureText('\\uFFFD').width;
  c.font = '48px monospace';
  out['__monospace__'] = c.measureText(s).width;
  return out;
}"""

# The init script marks the document through a DOM attribute, never a window
# global: an init script runs in Juggler's isolated world, so a `window.__x` it
# sets is invisible to page.evaluate(). The DOM is shared between worlds; JS
# expandos are not. Measurements themselves come back as page.evaluate()'s
# return value, which crosses worlds fine and is what every smoke arm uses.
INIT = ('(() => { const saw = (typeof window.setFontList === "function"); '
        'let applied = false; '
        'if (saw) { window.setFontList(%s); applied = true; } '
        'const mark = () => { try { document.documentElement.setAttribute('
        '"data-fl", JSON.stringify({saw: saw, applied: applied})); } catch (e) {} }; '
        'mark(); document.addEventListener("DOMContentLoaded", mark); })()')


def bundle_families(repo_root):
    """Every family name the Windows bundle carries, so a host family can be
    chosen that the bundle does NOT also supply -- otherwise "reachable" would
    not distinguish the host copy from the bundled one."""
    from fontTools.ttLib import TTFont, TTCollection
    fams = set()
    root = os.path.join(repo_root, "bundle", "fonts", "windows")
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                faces = (list(TTCollection(p).fonts) if fn.lower().endswith(".ttc")
                         else [TTFont(p, fontNumber=0, lazy=True)])
            except Exception:
                continue
            for face in faces:
                try:
                    for rec in face["name"].names:
                        if rec.nameID in (1, 16):
                            s = rec.toUnicode()
                            if s:
                                fams.add(s)
                except Exception:
                    continue
    return fams


def host_families():
    """Family names installed in C:\\Windows\\Fonts."""
    from fontTools.ttLib import TTFont, TTCollection
    fams = {}
    for p in glob.glob(r"C:\Windows\Fonts\*"):
        ext = os.path.splitext(p)[1].lower()
        if ext not in (".ttf", ".otf", ".ttc"):
            continue
        try:
            faces = (list(TTCollection(p).fonts) if ext == ".ttc"
                     else [TTFont(p, fontNumber=0, lazy=True)])
        except Exception:
            continue
        for face in faces:
            try:
                for rec in face["name"].names:
                    if rec.nameID in (1, 16):
                        s = rec.toUnicode()
                        if s:
                            fams.setdefault(s, p)
            except Exception:
                continue
    return fams


def measure(exe, families, camou_config, per_context_list, headful):
    """One launch, one context, one page -- the strongest isolation available,
    matching smoke's one_page(). headless is the default: these are advance-width
    measurements, which need no GL context, and an SSH session on Windows has no
    desktop to show a window on. --headful is available for a local run."""
    with sync_playwright() as pw:
        b = pw.firefox.launch(
            executable_path=exe, headless=not headful,
            env={**os.environ, "CAMOU_CONFIG": json.dumps(camou_config)})
        ctx = b.new_context()
        page = ctx.new_page()
        if per_context_list is not None:
            ctx.add_init_script(INIT % json.dumps(",".join(per_context_list)))
        page.goto("data:text/html,<h1>w</h1>")
        fl = page.evaluate('() => document.documentElement.getAttribute("data-fl")')
        widths = page.evaluate(JS_MEASURE, families)
        b.close()
    return {"widths": widths, "data_fl": fl}


def resolved(w, absent):
    return abs(w - absent) > 0.01


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--executable-path", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--repo-root", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    args = ap.parse_args()

    bundled = bundle_families(args.repo_root)
    if not bundled:
        print(f"FATAL: no family names read from {args.repo_root}\\bundle\\fonts\\windows -- "
              "--repo-root is wrong. Without the bundle list every host family looks "
              "host-only, and a 'reachable' reading could be the bundled copy.")
        return 1
    host = host_families()
    # A host family that the bundle does NOT also supply. Without this, a
    # "reachable" reading could be the bundled copy and would say nothing about
    # host fonts (CLAUDE.md lesson 4).
    candidates = sorted(set(host) - bundled)
    if not candidates:
        print("FATAL: every family in C:\\Windows\\Fonts is also in the bundle -- "
              "no host-only family exists to probe, so this run cannot answer #87.")
        return 1
    host_family = candidates[0]
    # The launch list deliberately excludes host_family, and is drawn from
    # families the bundle supplies so the launch itself is realistic.
    launch_list = sorted(bundled)[:40]
    probes = [host_family, "Arial", "Segoe UI"]

    print(f"host-only family under test: {host_family!r} (from {host[host_family]})")
    print(f"{len(candidates)} host-only families available; "
          f"{len(bundled)} families in bundle/fonts/windows")

    results = {
        "host_family": host_family,
        "host_family_file": host[host_family],
        "host_only_count": len(candidates),
        "bundle_family_count": len(bundled),
        "launch_list_size": len(launch_list),
        "env": {"executable": args.executable_path,
                "python": sys.version.split()[0],
                "headful": args.headful},
    }
    results["bare"] = measure(args.executable_path, probes, {}, None, args.headful)
    results["launch_list"] = measure(args.executable_path, probes,
                                     {"fonts": launch_list}, None, args.headful)
    results["per_context"] = measure(args.executable_path, probes, {},
                                     launch_list, args.headful)

    verdicts = []
    for name, r in (("bare", results["bare"]),
                    ("launch_list", results["launch_list"]),
                    ("per_context", results["per_context"])):
        w = r["widths"]
        print(f"[{name}] {w}")
        if abs(w["__absent1__"] - w["__absent2__"]) > 0.01:
            verdicts.append(f"{name}: VOID -- two different impossible families measured "
                            f"{w['__absent1__']} and {w['__absent2__']}, so width comparison "
                            f"can no longer tell a hit from a miss.")

    absent = results["bare"]["widths"]["__absent1__"]
    bare_host = resolved(results["bare"]["widths"][host_family], absent)
    list_host = resolved(results["launch_list"]["widths"][host_family],
                         results["launch_list"]["widths"]["__absent1__"])
    ctx_host = resolved(results["per_context"]["widths"][host_family],
                        results["per_context"]["widths"]["__absent1__"])

    # Positive control. MaskedFontListAppliesTo returns false when there is no
    # allowlist (gfx/thebes/gfxPlatformFontList.cpp:897-900), so a bare launch
    # is EXPECTED to reach host fonts. If it does not, the probe cannot see host
    # fonts at all and the two refusals below prove nothing.
    if not bare_host:
        verdicts.append(f"CONTROL FAILED: {host_family!r} is not reachable even under a bare "
                        f"launch, where no launch-level mask applies. The probe cannot see "
                        f"host fonts, so the refusals below are not evidence.")
    if list_host:
        verdicts.append(f"FAIL (#87): {host_family!r} is a host-installed family outside the "
                        f"launch `fonts` list and content still resolved it "
                        f"({results['launch_list']['widths'][host_family]} vs absent "
                        f"{results['launch_list']['widths']['__absent1__']}). The lookup-time "
                        f"filter does not exclude host fonts on Windows.")
    fl = results["per_context"]["data_fl"]
    if not fl or not json.loads(fl).get("applied"):
        verdicts.append(f"per_context: SETUP INVALID -- data-fl is {fl!r}, so setFontList did "
                        f"not run on the document that was measured. A context with no list "
                        f"is allowed everything, and its result says nothing.")
    elif ctx_host:
        verdicts.append(f"FAIL (#87): {host_family!r} is outside the per-context list and "
                        f"content still resolved it "
                        f"({results['per_context']['widths'][host_family]}). "
                        f"CamouIsFontAllowed does not exclude host fonts on Windows.")
    # U+FFFD codepoint fallback, which no family-name arm exercises.
    print(f"[U+FFFD] bare={results['bare']['widths']['__fffd__']} "
          f"launch_list={results['launch_list']['widths']['__fffd__']} "
          f"per_context={results['per_context']['widths']['__fffd__']}")

    results["verdicts"] = verdicts
    results["passed"] = not verdicts
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
    print("=== verdicts ===")
    for v in verdicts:
        print("  " + v)
    print("PASSED" if not verdicts else f"{len(verdicts)} problem(s)")
    return 0 if not verdicts else 1


if __name__ == "__main__":
    sys.exit(main())
```

Check it locally before it travels:
```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
python3 -m py_compile build-tester/scripts/probe_windows_fonts.py && echo "compiles"
python3 build-tester/scripts/probe_windows_fonts.py --help
```
Expected: `compiles` and the usage text. The `C:\Windows\Fonts` glob returns nothing on macOS,
so do not try to run it here.

- [ ] **Step 4: Ship the artifact and the script to the Windows host, and run**

```bash
gh api repos/lang315/camoufox/actions/runs/<BUILD_WINDOWS>/artifacts \
  --jq '.artifacts[] | "\(.id) \(.name) \(.size_in_bytes)"'
gh api repos/lang315/camoufox/actions/artifacts/<artifact id>/zip > /tmp/cfx-win.zip
scp /tmp/cfx-win.zip buildpc:/mnt/d/cfx-win.zip 2>/dev/null \
  || scp /tmp/cfx-win.zip buildpc:'D:\cfx-win.zip'
scp build-tester/scripts/probe_windows_fonts.py buildpc:'D:\probe_windows_fonts.py'
ssh buildpc 'powershell -Command "Expand-Archive -Force D:\cfx-win.zip D:\cfx-win"'
ssh buildpc 'dir /s /b D:\cfx-win\*.exe | findstr /I camoufox'
```
Unpack the inner archive if the outer one contains a second zip, until a `camoufox.exe` path
prints. The script resolves the bundle as `<--repo-root>/bundle/fonts/windows`, so whatever is copied
must land at that path. Either point `--repo-root` at an existing checkout on that machine, or
recreate just the one directory under a stub root:
```bash
ssh buildpc 'dir D:\camoufox\bundle\fonts\windows 2>&1 | findstr /C:"File(s)"' \
  || { ssh buildpc 'mkdir D:\camoufox-stub\bundle\fonts 2>nul'; \
       scp -r bundle/fonts/windows buildpc:'D:\camoufox-stub\bundle\fonts\windows'; }
```
and pass `--repo-root D:\camoufox` or `--repo-root D:\camoufox-stub` to match. If the family
count the script prints for the bundle is 0, the path is wrong — it will then pick a host
family the bundle also supplies, and "reachable" would not distinguish the host copy from the
bundled one.

Run it in the foreground on a held-open session. Detached jobs on that box are killed, so no
`nohup`, no `Start-Process`, no `&`:
```bash
ssh buildpc 'D:\camoufox-probe-venv\Scripts\python.exe D:\probe_windows_fonts.py \
  --executable-path D:\cfx-win\<path>\camoufox.exe \
  --repo-root D:\camoufox \
  --json D:\probe-windows.json' 2>&1 | tee .superpowers/sdd-fonts2/probe-windows.log
scp buildpc:'D:\probe-windows.json' .superpowers/sdd-fonts2/probe-windows.json
```
Expected: the host-only family it chose, three width tables, the U+FFFD line, and `PASSED`.
Any `CONTROL FAILED` or `SETUP INVALID` line means the run measured nothing — fix that before
reading the other verdicts, and never report a `FAIL`/`PASSED` from a run whose control failed.

- [ ] **Step 5: Post to #87 and commit the script**

First write `.superpowers/sdd-fonts2/issue-87-comment.md`, with every number copied out of
`.superpowers/sdd-fonts2/probe-windows.json` rather than recalled. It must carry: the binary
(`BUILD_WINDOWS`, its artifact id, `FIX_SHA`), the Windows and Python versions, the host-only
family chosen and the file it came from, all three width tables, the U+FFFD line, the
verdicts, and this NOT-verified paragraph:

> Not covered by this run: the macOS host. `Makefile`'s `package-macos: --fonts windows linux`
> bundles every OS except the target's own, because the host supplies its own, so the
> macOS host-font question stays unmeasured. Also not covered: any family not installed on
> this particular Windows machine, and any path this probe does not exercise — it measures
> family-name lookup and U+FFFD codepoint fallback only.

Then post it and read it back:

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
gh issue comment 87 -R lang315/camoufox --body-file .superpowers/sdd-fonts2/issue-87-comment.md
gh issue view 87 -R lang315/camoufox --json state,comments \
  --jq '.state + " | " + (.comments[-1].body[0:80])'
git add build-tester/scripts/probe_windows_fonts.py
git commit -m "test(#87): standalone native-Windows font probe

The smoke workflow is Linux-only -- .github/workflows/smoke.yml:18 is
runs-on: ubuntu-24.04 and is the only runner declaration in the file -- and
build-tester/run_tests.sh has no Windows branch, so the question #87 asks
cannot be answered by extending either. This is a standalone Playwright script
run by hand on a Windows host against a Windows artifact.

It measures family-name lookup and U+FFFD codepoint fallback under three
launches: bare, with a launch fonts key, and with a per-context setFontList.
The family under test is chosen at run time from C:\\Windows\\Fonts minus every
family bundle/fonts/windows supplies, so a 'reachable' reading cannot be the
bundled copy.

The bare launch is the positive control, not a third expectation.
MaskedFontListAppliesTo returns false when there is no allowlist
(gfx/thebes/gfxPlatformFontList.cpp:897-900), so host fonts ARE reachable
without a fonts key, and that is what proves the probe can see host fonts at
all. If it fails, the script reports CONTROL FAILED and does not present the
other two readings as evidence. It also refuses to score the per-context launch
unless the data-fl attribute proves setFontList ran on the document it
measured, and voids the run if two different impossible families measure
different widths.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Phase F — the PR

**Files:**
- Create: `.superpowers/sdd-fonts2/pr-body.md` (untracked)

**Interfaces:**
- Consumes: every earlier task's evidence — `FIX_SHA`, the three build ids, `SMOKE_B`,
  `SMOKE_FINAL`, `.superpowers/sdd-fonts2/gate.md`, `task7-evidence.md`,
  `probe-windows.json`, and the two issue numbers from Task 1.
- Produces: a merged PR.

- [ ] **Step 1: Read the branch back before describing it**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git fetch origin
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git rev-parse HEAD
gh run view <SMOKE_FINAL> -R lang315/camoufox --json conclusion --jq .conclusion
for id in <BUILD_LINUX> <BUILD_WINDOWS> <BUILD_MACOS>; do
  echo -n "$id "; gh run view "$id" -R lang315/camoufox --json conclusion --jq .conclusion
done
```
Every sha, id and number that goes into the body comes from this output or from the evidence
files, never from memory. Confirm the diff touches only `patches/font-hijacker.patch`,
`patches/font-list-spoofing.patch`, `.github/workflows/smoke.yml`,
`build-tester/scripts/probe_windows_fonts.py` and `docs/superpowers/`.

- [ ] **Step 2: Write `.superpowers/sdd-fonts2/pr-body.md`**

Use this skeleton, filling every angle-bracketed slot from Step 1 and the evidence files.
Keep the section order; a reviewer reads the NOT-verified list last on purpose.

```markdown
Part of #44. Closes #80, #82, #81. <Closes #83 — branch A only; on branch B write
"#83: measured, not fixed — see below" and use no closing keyword.>

The WebGL half of #44 stays open, so #44 carries no closing keyword either.

Head: `<FIX_SHA>`. Builds: linux-x86_64 `<BUILD_LINUX>`, windows-x86_64 `<BUILD_WINDOWS>`,
macos-arm64 `<BUILD_MACOS>`, all at that sha, all success. Final smoke: `<SMOKE_FINAL>`.

## #80 — `url()` web fonts are no longer refused

<what changed, two sentences, naming FontFaceImpl::CamouHasNonLocalSource and the three
call sites>

Evidence: smoke arm (k), run `<SMOKE_FINAL>`.

    <paste the two (k) log lines verbatim>

The arm builds its own probe face at run time with fontTools — unitsPerEm 1000, glyph `a`
advancing 2000 units — so 20 glyphs at 48px measure exactly 1920 if and only if that face
rendered. The bare launch is the control: the same bytes must render there, where
`IsFontAllowed` allows everything, or the arm reports the payload at fault instead of the
gate. #80's own recorded evidence could not do this: its probe measured 761.33 under both
launches and only the monospace reference moved, and its probe font was a bundled family, so
reference and measurement could resolve to the same typeface.

Before: <(k) line from the Phase B run `<SMOKE_B>`>.

## #82 and #81 — the two process-wide fallback caches

<what changed: the U+FFFD cached-family gate, the negative-cache read and write, the widened
MOZ_ASSERT>

Evidence: smoke arms (j), (j2), (i) and (i2), run `<SMOKE_FINAL>`.

    <paste the (i), (i2), (j) and (j2) log lines verbatim, including the tab pids>

Arm (i2) is new in this PR and is what backs `Closes #81`. Arm (i) only ever tested install,
render, install, render — the one sequence clear-on-install handles, because B's install runs
the clear after A's miss was written. Arm (i2) moves both installs ahead of both renders, so
both clears are spent before A's gated miss reaches
`gfx/thebes/gfxPlatformFontList.cpp:1403`. It was RED in run `<SMOKE_B>` and is GREEN here.

Both arms were repaired in this PR before they could measure anything. They scored
`final != named['Arial']`, and both values route through U+FFFD system fallback, so during a
real leak the cache answered both identically and the arm went green for the bug it guarded.
They now score by positive identification against the donor's own directly-named Tahoma
width, refuse to score unless the donor's automatic fallback actually landed on Tahoma, and
assert that donor and recipient shared a content process rather than assuming it.

Before: <(j)/(j2) lines from `<SMOKE_B>`, showing context B settling at the donor's width>.

#81 stays fixed by the read-path change rather than by clear-on-install; the clear is kept.

## #83 — <branch A: "the list now reaches the process that renders" | branch B: "measured, not fixed">

<Branch A: the arm (b2r) discriminator, the storage asymmetry it proved, the
PutString/hydration fix, and why hydration is in IsFunctionEnabledForWebIDL rather than in
HasFontList/IsFontAllowed — Preferences::InitStaticMembers asserts main thread or Servo
traversal, and CamouIsFontAllowed also runs on workers.>

<Branch B: arm (b2r) refuted H1; the MOZ_LOG line and what the `ctx=`/`hasList=` histogram
from run `<SMOKE_FINAL>` names; #83 stays open.>

Evidence: arms (b2) and (b2r), runs `<SMOKE_B>` (before) and `<SMOKE_FINAL>` (after).

    <paste the (b2), (b2r) and [b2r / ...] data-fl and pid lines from both runs>

## #88 — the 375.7 face

Arm (h') measures every family in `bundle/fonts/macos` in the mac context at 48px with the
same stack arm (h) uses, and prints whichever is within 0.01 of 375.70001220703125.

    <paste the "[arm h' / #88] ANSWER:" line and the enumerated-count line>

<If NO MATCH: the face is not a bundled mac family, so #88 falls through to its method 2 —
logging the resolved gfxFontEntry after refusal — which is not done here and stays open.>

## #87 — native Windows

Run by hand on a Windows host against artifact `<artifact id>` of build `<BUILD_WINDOWS>`,
using the new `build-tester/scripts/probe_windows_fonts.py`.

    <paste the host-only family chosen, the three width tables, the U+FFFD line, the verdicts>

## Test suites

- `build-tester`, headful on macOS arm64 build `<BUILD_MACOS>`: Grade `<g>` `<n>/<d>`.
  Failing checks: `<the classified list>`. `main`'s beta.31 baseline is Grade A 1061/1070.
  `checks-bundle.js` was deleted before the run so it rebuilt from
  `build-tester/src/lib/checks/index.ts`; a stale bundle is what produced 1064 in PR #84.
- `service-tester`, same binary, user-supplied proxy: Grade `<g>` `<n>/<d>`. A `0/0` is a
  vacuous run, not a pass (#89).

## Patch hygiene

`make dir` applies the whole stack with 0 FAILED
(`.superpowers/sdd-fonts2/make-dir-final.log`). Regenerating
`patches/font-list-spoofing.patch` through the workspace flow removed the four fuzz-1 hunks
PR #84 left behind; the file now has `<n>` hunks and applies with no fuzz.
`window-setter-seal.patch`'s `dom/base/FontListManager.cpp` hunk moves by an offset again
because this PR edits that file; it applies without fuzz.

## NOT verified

- **macOS host fonts.** `Makefile`'s `package-macos: --fonts windows linux` bundles every OS
  except the target's own, because the host supplies its own, so nothing here measures
  whether a macOS host's installed families stay unreachable. #87's probe covers Windows only.
- **The context-0 fail-open.** `CamouIsFontAllowed` returns true for every family when the
  context id resolves to 0 (`gfx/thebes/gfxPlatformFontList.cpp:1232-1239`). Every change in
  this PR inherits that, and changing it is a stated non-goal (CLAUDE.md lesson 5).
- **#80 outside the shape arm (k) measures.** Not measured over HTTP rather than a `data:`
  URI, with a quoted family name, through `document.fonts.add(new FontFace(...))`, or on
  native Windows or macOS.
- **Real load status.** `FontFaceImpl::SetStatus` still discards `aStatus`, so a `url()` face
  on an allowed family reports `loaded` even when the download fails. Filed as
  #<FONTFACE_STATUS_ISSUE>.
- **A mixed `src: local(X), url(Y)` rule** now reports `loaded` for a family the context's
  list excludes. No host font leaks — the `local()` refusal in
  `gfx/thebes/gfxUserFontSet.cpp:456-470` is untouched — but the two surfaces disagree.
- **`SpeechVoicesManager`** has the same storage asymmetry and is unmeasured. Filed as
  #<SPEECHVOICES_ISSUE>.
- **Still-ungated font read paths**, unchanged by this PR: `gfxFontGroup::GetDefaultFont()`'s
  shared-list last-resort walk; the non-shared `LookupInFaceNameLists` and `CommonFontFallback`
  else branches, dormant while `gfx.e10s.font-list.shared` is true; and `LookupLocalFont` on
  the macOS and Windows platform font lists, which a Linux guard cannot see.
- <Branch B only: **#83 itself.** H1 is refuted and the mechanism is named but not fixed.>
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create -R lang315/camoufox --base main --head fix/fonts-round2 \
  --title "fonts round 2: url() web fonts, the two fallback caches, and the per-context list (part of #44)" \
  --body-file .superpowers/sdd-fonts2/pr-body.md
gh pr view --json number,url,mergeable,headRefOid \
  --jq '"\(.number) \(.mergeable) \(.headRefOid[0:7]) \(.url)"'
git diff <FIX_SHA> HEAD --stat -- patches/
```
Expected: `MERGEABLE`, and the `git diff` over `patches/` is **empty**. The head sha is
deliberately *not* required to equal `FIX_SHA`: Task 7 Step 1 and Task 8 Step 5 both commit
after the builds were dispatched. What must hold is that nothing under `patches/` moved since
`FIX_SHA`, so the three binaries the evidence comes from are still the binaries this branch
builds. If that diff is non-empty, the builds and both suites must be re-run at the new sha
before the PR is opened.

- [ ] **Step 4: Final review**

Invoke `superpowers:requesting-code-review` against the branch. Give the reviewer the plan
path, the spec path, `.superpowers/sdd-fonts2/gate.md`, `task7-evidence.md`, and
`probe-windows.json`, and ask specifically for:

1. Whether every claim in the PR body is backed by a log line in a run the body names.
2. Whether each new or repaired arm can actually go red for the defect it guards, and what
   would make it green wrongly.
3. Lock order and thread affinity in branch A's `FontListManager` change.
4. Whether the NOT-verified list is complete against `CLAUDE.md`'s ungated-paths list.

Fix Critical and Important findings in place with new commits on the branch; carry Minors into
the body or into follow-up issues. If a fix changes any patch, re-run Task 6 Step 1, rebuild,
and re-run Task 7 — evidence must come from the commit that is actually merged.

- [ ] **Step 5: Merge**

Only after the review returns "ready to merge", the three builds and `SMOKE_FINAL` are green
at the head sha, and both suites have run:

```bash
gh pr merge <n> -R lang315/camoufox --merge
gh pr view <n> -R lang315/camoufox --json state,mergedAt,mergeCommit \
  --jq '"\(.state) \(.mergedAt) \(.mergeCommit.oid[0:7])"'
git checkout main && git pull
gh issue view 44 -R lang315/camoufox --json state --jq .state
gh issue view 81 -R lang315/camoufox --json state --jq .state
```
Expected: `MERGED` with a merge commit; `#44` still `OPEN` (the WebGL half); `#81` `CLOSED` on
branch A. On branch B, also confirm `#83` is still `OPEN`. Append the merge commit and the
final issue states to the ledger.

---

## Notes for the implementer

**Order.** Tasks 1 and 2 are independent and can run together. Task 3 must be committed before
Task 4 begins (`font-hijacker.patch` sorts first, so it is part of Task 4's
`first-checkpoint`). Task 5 needs Task 2's gate file and Task 4's commit. Task 6 needs 3, 4
and 5. Task 7 needs 6. Task 8 needs 6 and can run beside 7. Task 9 needs everything.

**Budget.** The spec allows two CI builds; this plan spends three, the extra being
`macos-arm64` for the two test suites, which run on the user's Mac. Plus two smoke runs
(Phase B and Phase D), each about fifteen minutes. A fourth build is needed only if the final
review changes a patch.

**The one thing that must not be skipped.** Every arm in Task 2 carries a
"what would make this GREEN wrongly" comment, and every verdict has a refusal branch that
prints "setup invalid", "control invalid" or "unmeasured" instead of a pass. Six times in the
previous fonts work an arm was scored against a reference that could equal the value under
test, and each time the result looked like a finding. If an arm's refusal branch is dropped to
make a run go green, the run stops being evidence.

