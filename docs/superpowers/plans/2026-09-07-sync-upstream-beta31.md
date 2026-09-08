# Sync fork `main` with upstream daijro/camoufox (beta.29 -> beta.31) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the 50 upstream commits (beta.29 -> beta.31, pythonlib 0.5.5 -> 0.5.6) into fork `main` via a `sync/upstream-beta31` branch in a fresh worktree, with every conflict resolved on a stated reason and the patch stack proven to apply before a build is dispatched.

**Assumption (stated, not verified with the user):** "sync main" means *upstream -> fork main*. The other reading -- syncing `fix/44-fonts-h2` with `main` -- is moot: that branch is 72 ahead / 0 behind `main`.

**Architecture:** Real `git merge --no-ff upstream/main` (not `gh repo sync`, which would force-push over the 215 fork-only commits). Same shape as PR #47 (beta.28 -> beta.29): tracking issue, per-file resolution table by category, mechanical local gates, then `make dir` as the patch-stack gate, then CI build + smoke.

**Tech Stack:** git worktree, GNU `patch`, `make dir`, pytest (pythonlib), `go test` (goapi drift gate), GitHub Actions `build.yml` (workflow_dispatch) + `smoke.yml` (run_id), build-tester `run_tests.sh`.

## Global Constraints

- `gh repo sync` is forbidden: fork `main` is 215 commits ahead of upstream; merge-base is `dbd511b` (2026-08-21 "README: Fix link").
- Every hand-written patch hunk must have balanced leading/trailing context; dry-run with `patch -p1 --forward -l --binary --dry-run < patches/x.patch` (CLAUDE.md). `git apply --check` is not a valid pre-flight.
- `build-tester/requirements.txt` keeps `playwright==1.55.0` (memory: newer -> 0/0 Grade F harness drift). Re-measuring against upstream `2b662a8` "Support Playwright 1.61+" is a follow-up, not a sync change.
- `build.yml` runs only on `workflow_dispatch` / `v*` tags. A PR does **not** auto-build. Feedback loop is 40-95 min per build; do not dispatch until Task 6 (`make dir`) is green.
- PR must close a tracking issue and carry evidence (command output with exit status), plus an explicit "NOT verified" section for anything skipped (CONTRIBUTING + user rules).
- No edits inside `camoufox-*/`; persist as patches.

## Measured state (2026-09-07)

```
main            55b4195  upstream.sh release=beta.29  pythonlib 0.5.5
upstream/main   eb5dc3b  upstream.sh release=beta.31  pythonlib 0.5.6
main...upstream/main : 215 fork-only / 50 upstream-only
```

`git merge-tree --write-tree --name-only main upstream/main` -> 10 conflicting files:

| File | Upstream side | Fork side | Category / default |
|---|---|---|---|
| `additions/camoucfg/MaskConfig.hpp` | `0969a94` adds `FontAllowlist()` / `HasFontAllowlist()` / `IsFontAllowed()` | `fee8712` webgl test config, `8a8940a` per-OS media codec matrix (device-faking #6) | **not convergent -- keep both**; adjacent-line collision |
| `additions/juggler/Helper.js` | `4132dd5` adds `ensureEventWithin()` + `kEventTimedOut`, imports `setTimeout` | `f458a11`/`67c83c7` `awaitTopic(topic, timeoutMs)` + `EventWatcher` timeouts, same `setTimeout` import | **convergent on the import, additive elsewhere -- keep both**; dedupe the `Timer.sys.mjs` import line |
| `additions/juggler/content/FrameTree.js` | `7911f4a` `camouUnsealFingerprintSetters(innerWindowId)` before init scripts (C++ seal, `window-setter-seal.patch`); `1e232f9`/`dc201dd` `mw:` world; `2b662a8` PW 1.61+ | `6e9c0e7` (#57) JS teardown: `docShell().disableSpoofSetters()` after init scripts on non-`about:` docs | **semantic -- CONFIRM**; default: take upstream seal, drop fork teardown (Task 4) |
| `build-tester/requirements.txt` | `17f873a` `playwright<1.63` | `playwright==1.55.0` + `marionette_driver` | **fork wins** (Global Constraints) |
| `patches/media-codec-spoofing.patch` | `03ac03c` + `17fe73a`: `media:spoof_codecs` gate, FF152 include order | `8a8940a`/`5861e99`/`d04a730`/`26d60e7`: per-OS codec + `mediaCapabilities` matrix, non-EME gate, `LOCAL_INCLUDES` | **semantic add/add -- hand-merge** (Task 5) |
| `patches/no-search-engines.patch` | `e459dc5` rewrites the stub hunk (`@@ -325`) to search-config **v2** (`recordType: engine`, one inert loopback engine) | `91052d7` two hunks: removes the `throw new Error("Could not find any engines")` (`@@ -245`) and edits the same stub hunk (`@@ -327`) | **partly convergent -- union**: upstream's stub hunk replaces the fork's; the fork's `@@ -245` throw-removal hunk is a different location, keep it (redundant once the stub carries one engine, but harmless; `make dir` gates it) |
| `pythonlib/camoufox/addons.py` | `6b8b086` re-download on missing manifest | `de7e6e8` Python-layer bug batch | **convergent-ish** -- take upstream, keep any fork-only fix the tests pin |
| `pythonlib/camoufox/fingerprints.py` | `fff2c73` appVersion from UA, `d6a806e` WebGL/screen coherence | `68661c8` drop `__camoufoxMissingSetters`, `3a22577`/`e0a57b5` availTop/pinned screen | **not convergent -- keep both** |
| `pythonlib/camoufox/utils.py` | `0e1f9a8` call site `get_screen_cons(headless) if has_display(env) else None`; `a80abb4` touchscreen; `8cb7914` PW floor warn; `fc3392e` bundle from executable_path | fork policy (PR #47): `get_screen_cons(_should_constrain_to_host_display(headless, env, virtual_display))`; `8f36f9b` one browser per OS (#45) | **semantic -- fork policy wins at the call site**, upstream mechanism elsewhere (Task 3) |
| `pythonlib/tests/test_addons.py` | `6b8b086` | `de7e6e8` | add/add -- **union of tests**; both must pass |

Auto-merged but semantically live (merge will NOT flag these):

- `patches/anti-font-fingerprinting.patch` -- both sides touched; upstream +67. Fork's `6e9c0e7` removed 17 lines here for #57. Re-read after Task 4 decision.
- `settings/camoucfg.jvv` -- upstream adds `media:spoof_codecs`, `disableWorldIsolation`; fork renamed `*voiceURI` -> `*voiceUri` (`a49ba82`, #72). Upstream jvv still says `*voiceURI` (line 292) -- confirm the fork's rename survives the auto-merge and that upstream's `voice-spoofing.patch` (+17) does not read the old key.
- `settings/properties.json` -- goapi `drift_test.go` compares it against `config.go`. New upstream keys without a goapi field turn the gate red (precedent `9440a6f`, `100b39a`).
- `pythonlib/camoufox/utils.py:773` docstring already says beta.29 restored world isolation and `mw:` works with `main_world_eval=True`; upstream's `disableWorldIsolation` is new. Memory file `ff152-vestigial-configs.md` is stale on this point -- do not "restore" anything from it.
- `.bak` files: upstream `92d79a8` deletes `patches/ghostery/Disable-Onboarding-Messages.patch.bak`, `patches/librewolf/urlbarprovider-interventions.patch.bak`; fork still has them. Merge deletes them; fine.
- `check_hunks.py` cited in PR #47 is **not tracked** in the repo (`git ls-files | grep check_hunks` -> 0). Do not cite it; Task 6 replaces it with the real gate.

## Fonts / in-flight `fix/44-fonts-h2` -- ordering decision (user)

Upstream `0969a94` + `70a22d8` add a font allowlist applied at lookup time (`MaskConfig.hpp::IsFontAllowed`, `font-hijacker.patch` +200, `font-system-fonts-css2.patch` -273, `system-ui-font-spoofing.patch`, `anti-font-fingerprinting.patch`). `fix/44-fonts-h2` (72 commits, +3611 lines in `font-hijacker.patch` / `font-list-spoofing.patch`, one uncommitted change) implements the fork's own `CamouIsFontAllowed`.

**Recommended:** sync `main` first (this plan), then rebase/merge `fix/44-fonts-h2` onto synced `main` and reconcile `CamouIsFontAllowed` against upstream's helper. Landing #44 first doubles the conflict surface (both sides of the merge would carry a different font gate).

Follow-ups this sync may obsolete (check, do not act here): `fix/pin-rust-toolchain` vs upstream `cb0d7a6` + `rust-vendor-unknown-fallback.patch`; playwright pin re-measure; `fix/57-setter-teardown` branch if Task 4 takes upstream's seal.

---

### Task 1: Tracking issue + worktree

**Files:**
- Create: worktree `.claude/worktrees/sync-upstream-beta31` on branch `sync/upstream-beta31` from `main`

- [ ] **Step 1: Open the tracking issue (mirrors #46)**

```bash
gh issue create -R lang315/camoufox \
  --title "Sync fork with upstream daijro/camoufox (beta.29 -> beta.31)" \
  --body "Upstream is at eb5dc3b (v152.0.4-beta.31, pythonlib 0.5.6); fork main is at 55b4195 (beta.29, pythonlib 0.5.5). 50 upstream commits, 10 conflicting files. Plan: docs/superpowers/plans/2026-09-07-sync-upstream-beta31.md"
```
Expected: prints the new issue URL. Record the number as `ISSUE`. (Opened: #85.)

- [ ] **Step 2: Create the worktree (REQUIRED SUB-SKILL: superpowers:using-git-worktrees)**

```bash
git -C /Users/lang/GolandProjects/github.com/lang315/camoufox fetch upstream origin
git -C /Users/lang/GolandProjects/github.com/lang315/camoufox worktree add .claude/worktrees/sync-upstream-beta31 -b sync/upstream-beta31 main
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/.claude/worktrees/sync-upstream-beta31
git log --oneline -1            # expect 55b4195
git status --short              # expect empty
```
Note: `build-tester/.venv` is untracked, so the worktree has none; `build-tester/run_tests.sh` creates one on first run, and Task 7 creates one for pytest.

- [ ] **Step 3: Put this plan in the worktree (it was written on `fix/44-fonts-h2`, untracked; `main` does not have it)**

```bash
cp /Users/lang/GolandProjects/github.com/lang315/camoufox/docs/superpowers/plans/2026-09-07-sync-upstream-beta31.md docs/superpowers/plans/
git add docs/superpowers/plans/2026-09-07-sync-upstream-beta31.md
git commit -m "docs(plan): sync upstream daijro/camoufox beta.29 -> beta.31"
```

- [ ] **Step 4: Commit nothing else yet; verify the merge preview matches this plan**

```bash
git merge-tree --write-tree --name-only main upstream/main | tail -n +2 | grep -v '^$' | head -12
```
Expected: exactly the 10 files in the table above. If the list differs, upstream moved since 2026-09-07 -- update the table before continuing.

---

### Task 2: Raw merge + the mechanical conflicts

**Files:**
- Modify: `build-tester/requirements.txt`, `patches/no-search-engines.patch`, `pythonlib/tests/test_addons.py`, `pythonlib/camoufox/addons.py`, `pythonlib/camoufox/fingerprints.py`, `additions/camoucfg/MaskConfig.hpp`, `additions/juggler/Helper.js`

- [ ] **Step 1: Merge**

```bash
git merge --no-ff upstream/main
```
Expected: `CONFLICT` lines for the 10 files; `git status --short | grep '^UU\|^AA'` lists exactly them.

- [ ] **Step 2: `build-tester/requirements.txt` -- fork wins**

```bash
git checkout --ours build-tester/requirements.txt
grep -n 'playwright\|marionette' build-tester/requirements.txt
```
Expected: `playwright==1.55.0` and `marionette_driver` present. `git add build-tester/requirements.txt`.

- [ ] **Step 3: `patches/no-search-engines.patch` -- union of hunks**

Two Firefox-side hunks are in play. Upstream `e459dc5` rewrites the stub hunk (`@@ -325,12 +325,65 @@ export class SearchEngineSelector`) to the search-config v2 shape the Rust selector deserializes (`recordType`, one inert engine whose URL is loopback); the fork's `91052d7` version of that same stub hunk is v1 and is superseded. The fork's other hunk (`@@ -245,12 +245,8 @@`, removes the `throw new Error("Could not find any engines in the filtered configuration")`) is a different location and does not exist upstream; keep it.

```bash
git diff dbd511b main -- patches/no-search-engines.patch | grep -E '^\+@@'            # fork: -245 and -327 hunks
git diff dbd511b upstream/main -- patches/no-search-engines.patch | grep -E '^\+@@'   # upstream: -325 hunk
```
Resolve by hand: keep the fork's `@@ -245` hunk, take upstream's `@@ -325` hunk verbatim, drop the fork's `@@ -327` hunk. Recount the header of the `-245` hunk only if you edited it (you should not need to).

```bash
grep -c '<<<<<<<' patches/no-search-engines.patch          # expect 0
grep -n 'recordType\|Could not find any engines' patches/no-search-engines.patch | head   # expect recordType present; the throw only as a '-' line
git add patches/no-search-engines.patch
```
Rationale for the PR body: upstream's v2 stub fixes daijro/camoufox#737 (search service never initialised, urlbar heuristic result gone); the fork's throw-removal is belt-and-braces for the same failure.

- [ ] **Step 4: `pythonlib/tests/test_addons.py` -- union**

Open the file; keep every test function from both `<<<<<<<` and `>>>>>>>` sides (rename only if two tests share a name and assert different things). Remove markers.

```bash
grep -c '<<<<<<<\|>>>>>>>' pythonlib/tests/test_addons.py   # expect 0
git add pythonlib/tests/test_addons.py
```

- [ ] **Step 5: `pythonlib/camoufox/addons.py` -- upstream mechanism, then run the union tests**

Take upstream's `6b8b086` body (re-download when the manifest is missing). Keep any fork line whose removal makes a fork test from Step 4 fail. Resolve, remove markers, then:

```bash
python3 -m venv .venv-sync && .venv-sync/bin/pip install -q -e pythonlib pytest
.venv-sync/bin/python -m pytest pythonlib/tests/test_addons.py -q
```
Expected: all pass. `git add pythonlib/camoufox/addons.py`.

- [ ] **Step 6: `pythonlib/camoufox/fingerprints.py` -- keep both**

Upstream adds appVersion-from-UA (`fff2c73`) and WebGL/screen coherence (`d6a806e`); fork removed `__camoufoxMissingSetters` (`68661c8`) and keeps browserforge `availTop` (`3a22577`). These touch different functions. Keep both; do **not** reintroduce `__camoufoxMissingSetters` (it reported false positives, #58).

```bash
grep -n '__camoufoxMissingSetters' pythonlib/camoufox/fingerprints.py   # expect no output
grep -c '<<<<<<<' pythonlib/camoufox/fingerprints.py                     # expect 0
git add pythonlib/camoufox/fingerprints.py
```

- [ ] **Step 7: `additions/camoucfg/MaskConfig.hpp` -- keep both**

Upstream's `FontAllowlist()`/`HasFontAllowlist()`/`IsFontAllowed()` block and the fork's media-codec / webgl helpers are unrelated; they collided on adjacent lines. Keep both blocks, remove markers.

```bash
grep -n 'IsFontAllowed\|FontAllowlist' additions/camoucfg/MaskConfig.hpp | head -3   # expect 3 hits
grep -c '<<<<<<<' additions/camoucfg/MaskConfig.hpp                                    # expect 0
git add additions/camoucfg/MaskConfig.hpp
```

- [ ] **Step 8: `additions/juggler/Helper.js` -- keep both, one import**

Both sides add `const {setTimeout, clearTimeout} = ChromeUtils.importESModule("resource://gre/modules/Timer.sys.mjs");`. Keep one. Keep the fork's `awaitTopic(topic, timeoutMs = DEFAULT_JUGGLER_EVENT_TIMEOUT_MS)` and `EventWatcher` timeout, and upstream's `ensureEventWithin()` + `kEventTimedOut` -- they bound different waits (topic observers vs synthesized-input acks).

```bash
grep -c 'Timer.sys.mjs' additions/juggler/Helper.js      # expect 1
grep -n 'ensureEventWithin\|awaitTopic' additions/juggler/Helper.js | head   # expect both
git add additions/juggler/Helper.js
```

- [ ] **Step 9: Commit the partial resolution? No.** Leave the merge open until Tasks 3-5 are resolved; one merge commit.

---

### Task 3: `pythonlib/camoufox/utils.py` -- fork policy at the call site

**Files:**
- Modify: `pythonlib/camoufox/utils.py`

**Interfaces:**
- Produces: `get_screen_cons(constrain_to_host: Optional[bool]) -> Optional[Screen]` (fork signature stays); call site stays `screen or get_screen_cons(_should_constrain_to_host_display(headless, env, virtual_display))`.

- [ ] **Step 1: Read both sides of the call-site hunk**

Fork (`main:920`): `get_screen_cons(_should_constrain_to_host_display(headless, env, virtual_display))`.
Upstream (`0e1f9a8`, `:797`): `(get_screen_cons(headless) if has_display(env) else None)`.

Upstream's fix corrects *its own* inverted guard; the fork never had that bug because `_should_constrain_to_host_display` already separates headless / real display / self-spawned Xvfb (PR #47, "fork policy wins": headless must NOT be clamped to the host monitor). Keep the fork's call site.

- [ ] **Step 2: Take upstream's additive pieces**

Keep from upstream: touchscreen digitizer plumbing (`a80abb4`), PW-floor warning (`8cb7914`), bundle-from-`executable_path` (`fc3392e`), `NotWritableError`/`ProfileDirectoryError` both (already merged in #47). Keep from fork: one-browser-per-OS (`8f36f9b`, #45).

- [ ] **Step 3: Verify**

```bash
grep -c '<<<<<<<' pythonlib/camoufox/utils.py                                  # expect 0
grep -n '_should_constrain_to_host_display(headless' pythonlib/camoufox/utils.py  # expect 1 (call site)
.venv-sync/bin/python -m pytest pythonlib/tests -q 2>&1 | tail -3
```
Expected: the same "N passed, M skipped" shape as PR #47 (186 passed, 5 skipped) plus upstream's new tests; zero failures. Failures in `test_utils*` about `get_screen_cons` mean upstream's new tests assume its call-site semantics -- adjust the *test* to the fork policy and say so in the PR body.

```bash
git add pythonlib/camoufox/utils.py pythonlib/tests
```

---

### Task 4: `FrameTree.js` -- #57 teardown vs upstream seal (CONFIRM with user before executing)

**Files:**
- Modify: `additions/juggler/content/FrameTree.js`
- Possibly modify: `patches/navigator-spoofing.patch`, `patches/screen-spoofing.patch`, `patches/playwright/0-playwright.patch`, `patches/anti-font-fingerprinting.patch` (the four `6e9c0e7` hunks that add `disableSpoofSetters`)

**Default decision:** take upstream's C++ seal (`window-setter-seal.patch`: window is created sealed; `camouUnsealFingerprintSetters(innerWindowId)` opens it only for init scripts). It closes the same tell as #57 at the C++ level -- the repo's stated design principle -- and covers the about:blank / pre-navigation case the fork's JS guard had to special-case.

- [ ] **Step 1: Resolve FrameTree.js**

Keep upstream's block (master-sandbox drop, `camouUnsealFingerprintSetters`, `_createIsolatedContext('', true)`, `disableWorldIsolation` branch, PW 1.61 changes). Drop the fork's `if (href && !href.startsWith('about:')) { this.docShell().disableSpoofSetters(); }` block.

```bash
grep -n 'camouUnsealFingerprintSetters' additions/juggler/content/FrameTree.js   # expect 1
grep -n 'disableSpoofSetters' additions/juggler/content/FrameTree.js              # expect 0
grep -c '<<<<<<<' additions/juggler/content/FrameTree.js                          # expect 0
git add additions/juggler/content/FrameTree.js
```

- [ ] **Step 2: The fork's `disableSpoofSetters` C++ hunks -- leave in place ONLY if `make dir` accepts them**

With no JS caller they are dead but harmless *in the patch files*. They are not harmless at the Firefox level: `6e9c0e7` edited the bodies of the Camoufox-created `dom/base/*Manager.cpp` files (the `@@ -0,0 +1,N @@` new-file hunks in `anti-font-fingerprinting`, `navigator-spoofing`, `screen-spoofing`) to consult a disabled flag inside `Is*FunctionEnabledForWebIDL`, and upstream's `window-setter-seal.patch` patches those same functions as *existing* files (`FontListManager.cpp @@ -72`, `NavigatorManager.cpp @@ -31/-43/-55/-67`, `ScreenDimensionManager.cpp @@ -30/-38`, plus Audio/FontSpacingSeed/SpeechVoices/Timezone/WebGLParams/WebRTCIP) expecting upstream's line numbers and context. If the fork's edits shifted those lines, the seal patch rejects in Task 6. The contingency is in Task 6 Step 3; do nothing more here.

- [ ] **Step 3: The arbiter is the smoke step, not this reasoning**

`smoke.yml` step `"spoofing setters are gone from window (#57 regression guard)"` (main `:174`) must be green in Task 8 with seal alone. If it goes red, revert Step 1 to keep the fork's teardown alongside the seal and note both mechanisms coexist.

---

### Task 5: `patches/media-codec-spoofing.patch` -- hand-merge

**Files:**
- Modify: `patches/media-codec-spoofing.patch`
- Modify: `settings/properties.json` (register `media:spoof_codecs` if upstream did not already)

- [ ] **Step 1: Extract both versions**

```bash
git show main:patches/media-codec-spoofing.patch     > /tmp/mc-fork.patch
git show upstream/main:patches/media-codec-spoofing.patch > /tmp/mc-up.patch
diff <(grep '^+++\|^@@' /tmp/mc-fork.patch) <(grep '^+++\|^@@' /tmp/mc-up.patch)
```
This shows which Firefox files/hunks each side touches. Fork: per-OS codec matrix + `mediaCapabilities:canPlayType` / `mediaCapabilities:decodingInfo` + non-EME gate + `LOCAL_INCLUDES` for `MaskConfig.hpp`. Upstream: `media:spoof_codecs` bool gate around the whole class + FF152 include order (`17fe73a`).

- [ ] **Step 2: Build the merged patch on top of the fork's version**

Start from `/tmp/mc-fork.patch`. Add upstream's `media:spoof_codecs` guard as the outermost condition of the same functions the fork already gates (the fork's non-EME gate stays inside it). Take upstream's include-order hunk verbatim (it targets FF152's actual order). Keep the fork's `LOCAL_INCLUDES` hunk. Every hunk you touch: recount `@@ -a,b +c,d @@` and keep leading == trailing context lines.

- [ ] **Step 3: Hunk arithmetic over EVERY patch, not just this one**

Git's textual merge of a diff-of-diff never recounts `@@` headers, so an *auto-merged* patch (`anti-font-fingerprinting.patch`: fork -17, upstream +67) can be silently corrupt too. This is the sweep PR #47 ran (its `check_hunks.py` was never committed; this is the replacement). It checks header counts and, for hand-edited hunks, the leading == trailing context balance that GNU `patch` charges against fuzz.

```bash
cat > /tmp/check_hunks.py <<'PY'
import re, sys, glob
bad = 0
for f in sorted(glob.glob('patches/**/*.patch', recursive=True)):
    p = open(f, encoding='utf-8', errors='replace').read().split('\n')
    i = 0
    while i < len(p):
        m = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', p[i])
        if not m:
            i += 1; continue
        a = int(m.group(2) if m.group(2) is not None else 1)
        b = int(m.group(4) if m.group(4) is not None else 1)
        j = i + 1; ca = cb = 0; lead = 0; trail = 0; seen_change = False
        while j < len(p) and not p[j].startswith(('@@', 'diff ', '--- ', '+++ ')):
            l = p[j]
            if l.startswith('\\'): j += 1; continue          # "\ No newline at end of file"
            if l.startswith('-'): ca += 1; seen_change = True; trail = 0
            elif l.startswith('+'): cb += 1; seen_change = True; trail = 0
            else:
                ca += 1; cb += 1
                if not seen_change: lead += 1
                else: trail += 1
            j += 1
        if (ca, cb) != (a, b):
            print(f'BAD COUNT {f}: {p[i]}  body={ca},{cb}'); bad += 1
        elif abs(lead - trail) > 2:
            print(f'UNBALANCED {f}: {p[i]}  lead={lead} trail={trail}'); bad += 1
        i = j
print('hunks OK' if not bad else f'{bad} bad hunks')
sys.exit(1 if bad else 0)
PY
python3 /tmp/check_hunks.py
```
Expected: `hunks OK`, exit 0. Known pre-existing off-by-one LAST hunks in `webgl-spoofing`, `font-hijacker`, `font-list-spoofing` (CLAUDE.md) may print as `BAD COUNT`; those are not yours -- confirm each reported line is one of those three files' last hunk, then proceed. Any `UNBALANCED` on a hunk you wrote in Step 2 must be fixed here, before Task 6 fetches a tarball.

- [ ] **Step 4: Register `media:spoof_codecs` in the schema if upstream did not**

```bash
grep -n 'media:spoof_codecs' settings/properties.json settings/camoucfg.jvv
```
Expected: present in both (upstream `0169975` "declare media:spoof_codecs"). If missing from `properties.json`, add `{ "property": "media:spoof_codecs", "type": "bool" },` next to the other `media:` / `mediaCapabilities:` entries.

```bash
git add patches/media-codec-spoofing.patch settings/properties.json
```

- [ ] **Step 5: Finish the merge commit**

```bash
git status --short | grep -E '^(UU|AA)'      # expect empty
git commit --no-edit                          # or write the "Merge upstream/main (beta.29 -> beta.31)" message in PR #47's shape
git log --oneline -1
```

---

### Task 6: Patch-stack gate -- `make dir` (the step PR #47 skipped and CI paid 1h20m for)

**Files:** none tracked; produces `camoufox-152.0.4-beta.31/` + `_READY` in the worktree (gitignored).

- [ ] **Step 1: Host deps (one-time on this Mac)**

```bash
bash scripts/install-deps.sh
python3 --version     # >= 3.11 (mach needs tomllib)
```

- [ ] **Step 2: Fetch, extract, apply**

```bash
cat upstream.sh                 # expect release=beta.31
make dir 2>&1 | tee /tmp/make-dir.log | tail -40
ls _READY
find camoufox-*/ -name '*.rej' | head
```
Expected: `_READY` exists; `find ... -name '*.rej'` prints nothing; `grep -c 'FAILED' /tmp/make-dir.log` -> 0.

- [ ] **Step 3: If a patch fails**

The log names the patch and hunk. Fix it in the patch file (balance context; `patch -p1 --forward -l --binary --dry-run < patches/<name>.patch` from inside `camoufox-*/` against a `make revert`ed tree), then `make revert && python3 scripts/patch.py` (or `make dir` again). Commit each patch fix separately: `fix(patches): <name> -- <what moved>`.

**Expected reject (Task 4 collision):** `window-setter-seal.patch` on one or more of `dom/base/{FontListManager,NavigatorManager,ScreenDimensionManager,...}.cpp` at `Is*FunctionEnabledForWebIDL`. Cause: the fork's `6e9c0e7` disabled-flag lines in those function bodies (now dead -- Task 4 dropped their only caller). Fix **now, in this PR, not as a follow-up**: remove the `6e9c0e7` additions from the new-file hunks in `patches/anti-font-fingerprinting.patch`, `patches/navigator-spoofing.patch`, `patches/screen-spoofing.patch` so the Manager bodies match what the seal hunks expect; recount those `@@ -0,0 +1,N @@` headers; re-run `/tmp/check_hunks.py`; re-run `make dir`. Keep the `nsDocShell::DisableSpoofSetters` / `nsIDocShell.idl` hunks in `0-playwright.patch` only if they still apply cleanly (they are additive); otherwise drop them too. Whatever is removed goes in the PR body under "#57: mechanism replaced by upstream seal".

- [ ] **Step 4: Confirm the voice key survives**

```bash
grep -rn 'voiceUri\|voiceURI' settings/camoucfg.jvv settings/properties.json patches/voice-spoofing.patch camoufox-*/dom/media/webspeech/synth/ 2>/dev/null | head
```
Expected: schema says `*voiceUri` (fork `a49ba82`, #72); no `voiceURI` reader in the applied source. If upstream's `voice-spoofing.patch` reintroduced `voiceURI`, align the patch to `voiceUri` and note it.

---

### Task 7: goapi drift gate + mechanical post-merge checks

**Files:**
- Modify: `goapi/pkg/config/config.go` (new fields)
- Test: `goapi/pkg/config/drift_test.go` (existing)

**Interfaces:**
- Produces: `Config.MediaSpoofCodecs *bool \`json:"media:spoof_codecs,omitempty"\``, `Config.DisableWorldIsolation *bool \`json:"disableWorldIsolation,omitempty"\``

- [ ] **Step 1: Run the gate red first**

```bash
cd goapi && go test ./pkg/config/ -run TestProducerSchemaDrift 2>&1 | tail -15; cd ..
```
Expected: FAIL naming `media:spoof_codecs` and `disableWorldIsolation` as schema keys with no producer field (precedent: `9440a6f`, `100b39a`). If it passes already, upstream keys were absorbed via `Extra` -- still add named fields so the API can set them.

- [ ] **Step 2: Register the fields**

In `goapi/pkg/config/config.go`, after `AllowAddonNewtab` (`:206`):

```go
	// Arrived with the beta.31 sync (upstream 0169975 declared
	// media:spoof_codecs, 1e232f9 added disableWorldIsolation).
	MediaSpoofCodecs      *bool `json:"media:spoof_codecs,omitempty"`
	DisableWorldIsolation *bool `json:"disableWorldIsolation,omitempty"`
```

- [ ] **Step 3: Gate green + full goapi suite**

```bash
cd goapi && go test ./... 2>&1 | tail -20; cd ..
```
Expected: `ok` for every package, exit 0. Also check whether `knownConfigOnlyKeys` in `drift_test.go` can shrink: `grep -c 'mediaCapabilities\|cssMedia\|screen:orientation' settings/properties.json` -- if > 0 after the merge, remove those keys from the set (the comment says to).

- [ ] **Step 4: Remaining mechanical checks**

```bash
grep '^release' upstream.sh                                    # release=beta.31
grep -m1 '^version' pythonlib/pyproject.toml                   # version = "0.5.6"
ls patches/ghostery/*.bak patches/librewolf/*.bak 2>&1          # No such file
.venv-sync/bin/python -m pytest pythonlib/tests -q 2>&1 | tail -2
.venv-sync/bin/python -c "import camoufox.utils, camoufox.server, camoufox.virtdisplay, camoufox.display; print('imports OK')"
grep -n 'beta.28\|beta.29' pythonlib/camoufox/utils.py CLAUDE.md README.md | head   # stale version mentions to update or leave with reason
```

- [ ] **Step 5: Commit**

```bash
git add goapi/pkg/config/config.go goapi/pkg/config/drift_test.go
git commit -m "fix(goapi): register media:spoof_codecs and disableWorldIsolation, the drift the beta.31 sync introduced"
git push -u origin sync/upstream-beta31
```

---

### Task 8: Build + runtime gates (CI, 40-95 min per build)

**Files:** none; evidence goes into the PR body.

- [ ] **Step 1: Dispatch a linux build on the sync branch**

```bash
gh workflow run build.yml -R lang315/camoufox --ref sync/upstream-beta31 -f build_target=linux-x86_64
gh run list -R lang315/camoufox --workflow=build.yml --branch sync/upstream-beta31 --limit 1
```
Record the run id as `BUILD_RUN`. Poll with `gh run watch $BUILD_RUN -R lang315/camoufox --exit-status` (or check back in ~60 min). A patch failure here means Task 6 was not run on the same tree -- do not "fix in CI".

- [ ] **Step 2: Smoke against that artifact**

```bash
gh workflow run smoke.yml -R lang315/camoufox --ref sync/upstream-beta31 -f run_id=$BUILD_RUN
```
Must be green: `"page.evaluate() is isolated from the page (#51/#62)"`, `"spoofing setters are gone from window (#57 regression guard)"` (Task 4 arbiter), `"per-context WebGL renderer beats the launch config (#44 regression guard)"`, `"launch-config timezone applies (#60)"`, `"reused profile can be re-fingerprinted (#63)"`, `Integration suite (all goapi tests vs real binary)`. Download `smoke-results` and quote the step results in the PR.

- [ ] **Step 3: build-tester (headful, Grade A baseline ~1050/1064)**

`smoke.yml` on `main` does not run `build-tester/run_tests.sh`. Dispatch a macOS build and run it locally:

```bash
gh workflow run build.yml -R lang315/camoufox --ref sync/upstream-beta31 -f build_target=macos-arm64
# after it completes:
MAC_RUN=$(gh run list -R lang315/camoufox --workflow=build.yml --branch sync/upstream-beta31 --json databaseId,displayTitle -q '.[] | select(.displayTitle|test("macos-arm64")) | .databaseId' | head -1)
gh run download "$MAC_RUN" -R lang315/camoufox -n CamoufoxBuilds-macos-arm64 -D /tmp/cfx-mac
cd /tmp/cfx-mac && zip=$(ls camoufox-*-mac.arm64.zip 2>/dev/null | head -1); [ -z "$zip" ] && zip=$(ls *.zip | head -1)
mkdir -p cf && unzip -q "$zip" -d cf
BIN=$(find cf -maxdepth 4 -type f \( -name camoufox-bin -o -name camoufox -o -name firefox \) | head -1); echo "$BIN"; chmod +x "$BIN"
cd /Users/lang/GolandProjects/github.com/lang315/camoufox/.claude/worktrees/sync-upstream-beta31/build-tester && ./run_tests.sh "/tmp/cfx-mac/$BIN" 2>&1 | tee /tmp/build-tester.log | tail -20
```
Expected: score within noise of the 1050/1064 baseline; a 0/0 Grade F is harness drift (playwright pin), not a spoof regression. Also run `service-tester` per its README against the same binary. (The unpack logic mirrors `smoke.yml` step "Unpack + locate firefox binary", `main:45`.)

- [ ] **Step 4: If build-tester cannot be run** -- say so in the PR under "NOT verified", with the reason, exactly as PR #47 did. Do not claim it.

---

### Task 9: PR

- [ ] **Step 1: Body in PR #47's shape**

Sections: `Closes #85`; conflict table by category (convergent / not convergent / semantic) with one-line reasons (copy from the Measured state table + Tasks 3-5 decisions); "Semantic overlaps the merge did not flag" (voiceUri, #57 seal, mw:/disableWorldIsolation, properties.json drift); Evidence (pytest tail, `go test ./...` tail, `make dir` tail + `_READY` + empty `.rej` find, smoke step results, build-tester score); NOT verified; Follow-up (rebase `fix/44-fonts-h2`, drop dead `disableSpoofSetters` hunks, `fix/pin-rust-toolchain` vs upstream `cb0d7a6`, playwright pin re-measure).

```bash
gh pr create -R lang315/camoufox --base main --head sync/upstream-beta31 \
  --title "Sync upstream daijro/camoufox: beta.29 -> beta.31" --body-file /tmp/pr-body.md
```

- [ ] **Step 2: After merge**

```bash
cd /Users/lang/GolandProjects/github.com/lang315/camoufox
git checkout fix/44-fonts-h2 && git stash   # the uncommitted font-list-spoofing.patch change
git fetch origin && git merge origin/main    # or rebase; reconcile CamouIsFontAllowed vs upstream IsFontAllowed
git worktree remove .claude/worktrees/sync-upstream-beta31
```
