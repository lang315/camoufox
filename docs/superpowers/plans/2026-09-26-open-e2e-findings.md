# Open e2e findings: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrub the former identity from the fork's history (W0). Then fix
#162, #163, #164 and #166, and measure #165 and #171 until their fixes are
known (W1-W4).

**Architecture:** There are six workstreams, and each one is its own PR, except W0,
which is a force-push tracked by an issue:
- **W0** rewrites history once, before anything else.
- **W2** (goapi) and **W3** (pythonlib) need no browser build.
- **W1** (browser) is one build.
- **W4** is measurement that runs alongside W1.

Every fix is proven by the entry in `e2e/known.py` that records it: a strict
entry flips to `FIXED?`, or a non-strict one stays green on 3 dispatches.

**Tech Stack:** git-filter-repo, Go 1.22 (goapi), Python 3.11+ with pytest
(pythonlib and e2e), Firefox patches (GNU patch), and Juggler JS.

**Spec:** `docs/superpowers/specs/2026-09-26-open-e2e-findings-design.md`.
Read it first. The root-cause table there is what every task argues from.

## Global Constraints

- Pass `--repo lang315/camoufox` on every `gh` call.
- Every PR is tied to an issue and carries evidence: commands with their
  exit status and run ids.
- Merge only after the checks are green, and without `--auto`.
- Never poll background jobs with `sleep`, `ps`, `pgrep` or `top`.
- Read a job's log with
  `gh api --allow-escape-sequences repos/lang315/camoufox/actions/jobs/<id>/logs`.
- Hand-written patch hunks keep their leading and trailing context balanced.
  Pre-flight with `patch -p1 --forward -l --binary --dry-run < patches/x.patch`,
  never with `git apply --check`.
- Never run `make workspace` on `font-list-spoofing.patch`. Rebuild the tree at
  its own position instead (CLAUDE.md, #131).
- Removing a ledger entry needs one of two things. A strict entry is removed
  only after the run that reports its `FIXED?`. A non-strict entry is removed
  only after 3 consecutive green dispatches on every host it lists. The PR
  quotes each run id, resolved to its build and branch (CLAUDE.md lesson 9).
- New tests are shown red before the fix, with the output pasted.
- **Never write the former name or the personal email into any tracked file,
  commit message, issue or PR body.** The only copy of the email lives in
  `~/camoufox-scrub/mailmap`, which is outside the repo and never uploaded.
- The target identity is `Lãng <30039912+lang315@users.noreply.github.com>`.
- The W0 force-push happens only after the maintainer says so explicitly **at
  that moment**. An earlier approval of this plan is not that approval.
- `CAMOUFOX_NO_GENERIC_PREFS=1` is a test hook. It exists only so W1 can be
  measured without W3's prefs (lesson 4).

## File map

| File | Workstream | Change |
|---|---|---|
| `scripts/history_rewrite/rewrite_sha_refs.py` (new) | W0 | rewrite sha references through filter-repo's commit-map |
| `scripts/history_rewrite/test_rewrite_sha_refs.py` (new) | W0 | its unit test |
| `docs/history-rewrite-2026-09.md` (new, made during W0) | W0 | old → new sha map |
| `goapi/download.go`, `goapi/context.go`, `goapi/download_path_test.go` (new) | W2 | #166.1 |
| `goapi/pkg/fingerprint/generator.go`, `goapi/pkg/fingerprint/window_test.go` (new) | W2 | #166.2, #166.4 |
| `goapi/page.go`, `goapi/frame_wait_test.go` (new) | W2 | #166.5 |
| `goapi/fontenv.go` (new), `goapi/fontenv_test.go` (new), `goapi/launch.go` | W2 | #162b, #162 (B, goapi half) |
| `goapi/cmd/e2edriver/main.go`, `e2e/drivers/go.py` | W2 | the go driver passes `webrtc_ip` |
| `pythonlib/camoufox/utils.py`, `pythonlib/tests/test_generic_font_prefs.py` (new) | W3 | #162 (B) |
| `pythonlib/camoufox/fingerprints.py` | W3 | #163 (pythonlib half), #164a |
| `pythonlib/camoufox/sync_api.py`, `pythonlib/camoufox/async_api.py` | W3 | #164a (record the launch window) |
| `pythonlib/tests/test_context_geometry.py` (new) | W3 | #164a |
| `README.md`, `pythonlib/README.md`, `e2e/drivers/playwright_drivers.py` | W3 | #164b |
| `tests/patches/generic-monospace-launch-mask.py` (new) | W1 | the #162 RED-first guard |
| `patches/webrtc-launch-ip-fallback.patch` (new) | W1 | #163 |
| `patches/font-list-spoofing.patch` | W1 | #162 (A) |
| `additions/juggler/NetworkObserver.js` | W1 | #166.3 |
| `e2e/journeys/test_03_network.py` | W1 | the per-context-over-launch WebRTC case |
| `e2e/probes/emoji_timing.py` (new) | W4 | the #165 probe |
| `e2e/journeys/test_08_lifecycle.py`, `e2e/drivers/playwright_drivers.py`, `.github/workflows/e2e.yml` | W4 | #171 MOZ_LOG capture |
| `e2e/known.py` | all | ledger updates |

---

## Phase 0: land the spec and plan, and prepare W0

### Task 0: The sha-reference rewriter, and landing the spec and plan

**Files:**
- Create: `scripts/history_rewrite/rewrite_sha_refs.py`
- Create: `scripts/history_rewrite/test_rewrite_sha_refs.py`
- Already on this branch: the spec and this plan.

**Interfaces:**
- Produces: `python3 scripts/history_rewrite/rewrite_sha_refs.py <commit-map>`.
  It rewrites tracked text files in place (not `*.patch`, and not binaries),
  prints each changed path, and prints `N files rewritten` to stderr.
- Produces: `python3 scripts/history_rewrite/rewrite_sha_refs.py --dump-map <commit-map> <out.md>`,
  which writes the Markdown old → new table.

- [ ] **Step 1: Write the failing test**

```python
# scripts/history_rewrite/test_rewrite_sha_refs.py
import textwrap
from pathlib import Path

import rewrite_sha_refs as r

OLD = "a9f1682" + "0" * 33
NEW = "c6e0ae9" + "1" * 33
UPSTREAM = "e25a16b" + "2" * 33  # unchanged by the rewrite: not in the map


def write_map(tmp_path: Path) -> Path:
    p = tmp_path / "commit-map"
    p.write_text(textwrap.dedent(f"""\
        old                                      new
        {OLD} {NEW}
        {UPSTREAM} {UPSTREAM}
        {"b" * 40} {"0" * 40}
        """))
    return p


def test_a_short_sha_is_rewritten_at_its_own_length(tmp_path):
    m = r.load_map(write_map(tmp_path))
    assert r.rewrite_text("fixed in a9f1682, see a9f16820", m) == f"fixed in {NEW[:7]}, see {NEW[:8]}"


def test_unchanged_deleted_and_non_sha_tokens_are_left_alone(tmp_path):
    m = r.load_map(write_map(tmp_path))
    text = f"upstream {UPSTREAM[:7]}, pruned {'b' * 7}, width 1234567, hash deadbeef00"
    assert r.rewrite_text(text, m) == text


def test_dump_map_lists_only_changed_commits(tmp_path):
    out = tmp_path / "map.md"
    r.dump_map(write_map(tmp_path), out)
    body = out.read_text()
    assert f"| `{OLD}` | `{NEW}` |" in body
    assert UPSTREAM not in body and "b" * 40 not in body
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd scripts/history_rewrite && python3 -m pytest -q test_rewrite_sha_refs.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'rewrite_sha_refs'`.

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Rewrite commit-sha references in tracked files after `git filter-repo` (W0).

filter-repo writes .git/filter-repo/commit-map ("old new" per line, header first,
all-zero new = pruned). Every 7-40 hex token in a tracked text file that is a
unique prefix of a CHANGED commit is replaced by the new sha at the same length.
Tokens of unchanged commits (upstream history) and non-sha hex are left alone.
*.patch files are skipped: their `index` lines are blob hashes, not commits.

    python3 rewrite_sha_refs.py <commit-map>
    python3 rewrite_sha_refs.py --dump-map <commit-map> <out.md>
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict

HEX = re.compile(r"\b[0-9a-f]{7,40}\b")


def load_map(path) -> Dict[str, str]:
    changed = {}
    for line in Path(path).read_text().splitlines()[1:]:
        old, new = line.split()
        if old != new and set(new) != {"0"}:
            changed[old] = new
    return changed


def rewrite_text(text: str, changed: Dict[str, str]) -> str:
    by_prefix: Dict[str, list] = {}
    for old in changed:
        by_prefix.setdefault(old[:7], []).append(old)

    def sub(mo):
        token = mo.group(0)
        if token.isdigit():
            return token
        hits = [o for o in by_prefix.get(token[:7], []) if o.startswith(token)]
        return changed[hits[0]][: len(token)] if len(hits) == 1 else token

    return HEX.sub(sub, text)


def dump_map(map_path, out_path) -> None:
    rows = sorted(load_map(map_path).items())
    lines = [
        "# History rewrite, 2026-09",
        "",
        "W0 of `docs/superpowers/specs/2026-09-26-open-e2e-findings-design.md` rewrote the",
        "fork's author and committer identities. Issue and PR bodies and Actions runs still",
        "name the OLD shas; this table resolves them. Commits not listed kept their sha.",
        "",
        "| old | new |",
        "|---|---|",
        *(f"| `{o}` | `{n}` |" for o, n in rows),
        "",
    ]
    Path(out_path).write_text("\n".join(lines))


def main(argv) -> int:
    if argv[:1] == ["--dump-map"]:
        dump_map(argv[1], argv[2])
        return 0
    changed = load_map(argv[0])
    files = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    n = 0
    for name in filter(None, files.split("\0")):
        path = Path(name)
        if path.suffix == ".patch" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = rewrite_text(text, changed)
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(name)
            n += 1
    print(f"{n} files rewritten", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run it and watch it pass**

Run: `cd scripts/history_rewrite && python3 -m pytest -q test_rewrite_sha_refs.py`
Expected: `3 passed`.

- [ ] **Step 5: Open an issue, commit, open the PR, merge**

```bash
gh issue create --repo lang315/camoufox --title "Scrub the former maintainer identity from the fork's git history" \
  --body "W0 of docs/superpowers/specs/2026-09-26-open-e2e-findings-design.md. Evidence is posted here, because a history rewrite cannot be a PR."
git add scripts/history_rewrite docs/superpowers
git commit -m "docs, scripts: open-findings spec and plan; sha-reference rewriter for W0"
git push -u origin docs/open-findings-spec
gh pr create --repo lang315/camoufox --base main --title "docs: open-findings spec and plan, W0 tooling" --body "<issue link, test output from Step 4>"
```

Wait for the gate to go green, then run `gh pr merge <n> --repo lang315/camoufox --squash --delete-branch`.

---

## W0: identity scrub

### Task 1: Rewrite on a mirror, and verify (no push)

**Files:** none in the working checkout. Everything happens in `~/camoufox-scrub/`.

- [ ] **Step 1: Freeze, and write the mailmap outside the repo**

```bash
gh pr list --repo lang315/camoufox --state open          # expect: empty
gh run list --repo lang315/camoufox --status in_progress # expect: empty
mkdir -p ~/camoufox-scrub && cd ~/camoufox-scrub
# Two lines, keyed by EMAIL, so the former name never has to be written down:
#   line 1 maps every commit using the personal Gmail address
#   line 2 maps every commit using the noreply address (fixes the name on web merges)
printf '%s\n' \
  'Lãng <30039912+lang315@users.noreply.github.com> <PERSONAL_GMAIL_ADDRESS>' \
  'Lãng <30039912+lang315@users.noreply.github.com> <30039912+lang315@users.noreply.github.com>' > mailmap
```

Replace `PERSONAL_GMAIL_ADDRESS` in the file by hand. This file is the only
place the address is written down.

- [ ] **Step 2: Take a mirror clone and an offline backup**

```bash
cd ~/camoufox-scrub
git clone --mirror https://github.com/lang315/camoufox.git camoufox.git
git -C camoufox.git show-ref --heads --tags > refs-before.txt
git -C camoufox.git rev-list --all --count > count-before.txt     # expect 1289 or more
git -C camoufox.git bundle create ../camoufox-pre-scrub.bundle --all
```

Keep `~/camoufox-pre-scrub.bundle` offline. It holds the old identity.

- [ ] **Step 3: Rewrite**

```bash
cd ~/camoufox-scrub/camoufox.git
git filter-repo --mailmap ../mailmap --force
cp filter-repo/commit-map ../commit-map
```

- [ ] **Step 4: Verify before any push, and paste every output into the W0 issue**

```bash
cd ~/camoufox-scrub/camoufox.git
git log --all --format='%an <%ae>%n%cn <%ce>' | sort | uniq -c        # expect: only Lãng <noreply>, upstream authors, GitHub, Claude
git log --all --format='%an%n%cn%n%ae%n%ce%n%B' | grep -ciE -f <(sed -n 's/.*<\(.*\)> <\(.*\)>/\2/p' ../mailmap | head -1)   # expect 0
git rev-list --all --count                                             # expect = count-before.txt
old_main=$(grep ' refs/heads/main$' ../refs-before.txt | cut -d' ' -f1)
new_main=$(git rev-parse main)
git -C ~/GolandProjects/github.com/lang315/camoufox rev-parse "$old_main^{tree}"; git rev-parse "$new_main^{tree}"  # expect identical
up=$(git -C ~/GolandProjects/github.com/lang315/camoufox rev-parse e1b227c^)   # the last upstream commit before the first rewritten one
git cat-file -e "$up^{commit}" && git merge-base --is-ancestor "$up" main; echo "upstream history unchanged: $?"   # expect 0: same sha, still under main
```

The grep for the old name is done by eye on the `uniq -c` output. Do not
write the name into a command that ends up in shell history. If any check
differs from what is expected, stop. The mirror is disposable, so fix and
re-run from Step 2.

- [ ] **Step 5: Add the map and rewrite the in-repo references on the rewritten `main`**

```bash
cd ~/camoufox-scrub && git clone camoufox.git work && cd work
python3 ~/GolandProjects/github.com/lang315/camoufox/scripts/history_rewrite/rewrite_sha_refs.py ../commit-map
python3 ~/GolandProjects/github.com/lang315/camoufox/scripts/history_rewrite/rewrite_sha_refs.py --dump-map ../commit-map docs/history-rewrite-2026-09.md
git add -A && git -c user.name='Lãng' -c user.email='30039912+lang315@users.noreply.github.com' \
  commit -m "docs: resolve pre-rewrite shas through docs/history-rewrite-2026-09.md"
git push origin main   # into the local mirror only
```

- [ ] **Step 6: Check that every 7-40 hex token in docs still resolves**

```bash
cd ~/camoufox-scrub/work
git ls-files -z '*.md' '*.yml' '*.py' | xargs -0 grep -ohE '\b[0-9a-f]{7,40}\b' | grep -v '^[0-9]*$' | sort -u |
  while read t; do git cat-file -e "$t^{commit}" 2>/dev/null || echo "unresolved $t"; done | head -50
```

Expected: every `unresolved` line is a non-commit hex value (a hash in
prose, a canvas checksum and so on), never a sha listed in the old column of
`docs/history-rewrite-2026-09.md`. Check that with
`grep -c "<token>" docs/history-rewrite-2026-09.md`, which should be 0 for each.

### Task 2: The force-push (needs the maintainer's explicit go-ahead)

- [ ] **Step 1: Stop and ask.** Post the Task 1 outputs to the W0 issue. Tell the
  maintainer what the push does, in the words of the spec's "What a rewrite
  changes" list. Wait for an explicit yes in this session. Do not continue
  without it.
- [ ] **Step 2: Push heads and tags only**

```bash
cd ~/camoufox-scrub/camoufox.git
git push --force origin 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
```

- [ ] **Step 3: Check after the push**

```bash
gh release view v152.0.4-beta.31-fork.1 --repo lang315/camoufox --json assets -q '.assets[].name'   # the same assets as before
gh workflow run e2e.yml --repo lang315/camoufox -f release=v152.0.4-beta.31-fork.1                # watch it go green
cd ~/GolandProjects/github.com/lang315/camoufox && git fetch origin && git checkout main && git reset --hard origin/main
```

The last line is the local checkout. It had no unpushed work, as confirmed in
Task 1 Step 1.

- [ ] **Step 4: Maintainer actions, listed in the issue:**
  - In GitHub → Settings → Emails, turn on "Keep my email addresses private"
    and "Block command line pushes that expose my email".
  - Optionally, open a GitHub Support ticket to purge cached views and the
    `refs/pull/*` refs that still hold the old commits.
  - Re-clone every other checkout, such as the build PC's.
- [ ] **Step 5: Close the W0 issue**, with the post-push run id.

---

## W2: goapi (no browser build)

Branch `fix/166-goapi` from the post-W0 `main`. Open one issue per PR only if
the existing #166 and #162 do not already cover it; they do.

### Task 3: `Download.Path` returns `<dir>/<uuid>` (#166.1)

**Files:**
- Modify: `goapi/context.go:13-19` (field), `goapi/download.go:21-34,58-62,149`
- Create: `goapi/download_path_test.go`

- [ ] **Step 1: Write the failing test**

```go
package camoufox

import (
	"path/filepath"
	"testing"
)

// The browser saves a download as <downloadsDir>/<uuid> (juggler
// TargetRegistry.js:75-80), never under the suggested name (#166).
func TestDownloadPathIsDirPlusUUID(t *testing.T) {
	d := &Download{UUID: "ae100b25-e025-4039-b96b-9dea5b347235", SuggestedFileName: "file.bin", downloadsDir: "/tmp/dl"}
	if got, want := d.Path(), filepath.Join("/tmp/dl", "ae100b25-e025-4039-b96b-9dea5b347235"); got != want {
		t.Fatalf("Path() = %q, want %q", got, want)
	}
	if got := (&Download{UUID: "x"}).Path(); got != "" {
		t.Fatalf("Path() with no downloads dir = %q, want empty (nothing was saved)", got)
	}
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd goapi && go test -run TestDownloadPathIsDirPlusUUID .`
Expected: FAIL, with `Path() = "/tmp/dl/file.bin"`.

- [ ] **Step 3: Implement**

In `goapi/context.go`, add a field to `BrowserContext`:

```go
	dlMu         sync.Mutex
	downloadsDir string // from SetDownloadOptions; the browser saves downloads here as <uuid>
```

In `goapi/download.go`, `SetDownloadOptions`: after the successful `Call`,
before `return nil`, add:

```go
	c.dlMu.Lock()
	c.downloadsDir = opts.DownloadsDir
	c.dlMu.Unlock()
```

Replace `Path()` with:

```go
// Path returns where the browser saved the download: <DownloadsDir>/<UUID>.
// The browser names the file by its UUID (juggler TargetRegistry.js), never by
// SuggestedFileName. Empty when SetDownloadOptions set no directory, in which
// case nothing was saved.
func (d *Download) Path() string {
	if d.downloadsDir == "" {
		return ""
	}
	return filepath.Join(d.downloadsDir, d.UUID)
}
```

At `download.go:149`, replace `downloadsDir: "", // caller sets via SetDownloadOptions` with:

```go
			downloadsDir:      c.currentDownloadsDir(),
```

Then add:

```go
func (c *BrowserContext) currentDownloadsDir() string {
	c.dlMu.Lock()
	defer c.dlMu.Unlock()
	return c.downloadsDir
}
```

Extend `TestDownloadOnDownload` (`goapi/download_test.go`). After `dl.Wait`
succeeds, add:

```go
	body, err := os.ReadFile(dl.Path())
	if err != nil || string(body) != "download content" {
		t.Fatalf("ReadFile(Path()=%q) = %q, %v; want the served body", dl.Path(), body, err)
	}
```

- [ ] **Step 4: Run it and watch it pass**

Run: `cd goapi && go test -run 'TestDownloadPath' . && CAMOUFOX_BIN=<fork.1 binary> go test -run TestDownloadOnDownload .`
Expected: PASS for both.

- [ ] **Step 5: Commit**: `git commit -am "fix(goapi): Download.Path is <downloads dir>/<uuid>, where the browser saves it (#166)"`

### Task 4: A window that fits the screen, and the voice block (#166.2, #166.4)

**Files:**
- Modify: `goapi/pkg/fingerprint/generator.go` (in `Generate` after `applyPreset`, plus a new `applyWindow`)
- Create: `goapi/pkg/fingerprint/window_test.go`

- [ ] **Step 1: Write the failing tests**

```go
package fingerprint

import (
	"math/rand/v2"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// #166: goapi left window.outer* unset, so browser-init.patch kept 1280x1040
// on any screen. Every draw must satisfy outer <= avail <= screen, with a
// visible taskbar (avail height < screen height).
func TestGeneratedWindowFitsScreen(t *testing.T) {
	for _, osKey := range []string{"windows", "macos", "linux"} {
		rng := rand.New(rand.NewPCG(1, 2))
		for i := 0; i < 300; i++ {
			cfg := &config.Config{}
			if err := Generate(cfg, Options{OS: osKey, Rand: rng}); err != nil {
				t.Fatal(err)
			}
			sw, sh := *cfg.ScreenWidth, *cfg.ScreenHeight
			aw, ah := *cfg.ScreenAvailWidth, *cfg.ScreenAvailHeight
			if cfg.WindowOuterWidth == nil || cfg.WindowOuterHeight == nil {
				t.Fatalf("%s draw %d: window.outer* unset", osKey, i)
			}
			ow, oh := *cfg.WindowOuterWidth, *cfg.WindowOuterHeight
			if !(ow <= aw && aw <= sw && oh <= ah && ah < sh) {
				t.Fatalf("%s draw %d: screen %dx%d avail %dx%d outer %dx%d", osKey, i, sw, sh, aw, ah, ow, oh)
			}
		}
	}
}

// #166: with no voices for linux and no block flag, the browser registered
// the host's own voices (Microsoft voices on a Windows host).
func TestGenerateAlwaysBlocksHostVoices(t *testing.T) {
	for _, osKey := range []string{"windows", "macos", "linux"} {
		cfg := &config.Config{}
		if err := Generate(cfg, Options{OS: osKey, Rand: rand.New(rand.NewPCG(3, 4))}); err != nil {
			t.Fatal(err)
		}
		if cfg.VoicesBlockIfNotDefined == nil || !*cfg.VoicesBlockIfNotDefined {
			t.Fatalf("%s: voices:blockIfNotDefined not set", osKey)
		}
	}
}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd goapi && go test ./pkg/fingerprint -run 'TestGeneratedWindowFitsScreen|TestGenerateAlwaysBlocksHostVoices'`
Expected: FAIL with `window.outer* unset`, and with `voices:blockIfNotDefined not set`.

- [ ] **Step 3: Implement**

In `Generate`, right after `targetOS := osFromPlatform(preset.Navigator.Platform)`, add:

```go
	applyWindow(cfg, targetOS)
	// Mirrors pythonlib utils.py:1278-1294: the block is pinned explicitly, so
	// an empty voice list (linux ships none) cannot fall through to the host's
	// native voices (#166).
	if cfg.VoicesBlockIfNotDefined == nil {
		cfg.VoicesBlockIfNotDefined = config.Bool(true)
	}
```

Then add:

```go
// applyWindow mirrors pythonlib's fix_screen_no_taskbar and
// clamp_window_dimensions (pythonlib/camoufox/fingerprints.py:349, :471): a
// maximised window on the sampled screen, so outer <= avail <= screen with a
// visible taskbar. Presets carry no window size, and without this the browser
// keeps browser-init.patch's 1280x1040 on any screen (#166). Inner is left to
// the browser, which lays it out inside the real window.
func applyWindow(cfg *config.Config, targetOS string) {
	if cfg.ScreenWidth == nil || cfg.ScreenHeight == nil {
		return
	}
	sw, sh := *cfg.ScreenWidth, *cfg.ScreenHeight
	aw, ah := sw, sh
	if cfg.ScreenAvailWidth != nil {
		aw = min(*cfg.ScreenAvailWidth, sw)
	}
	if cfg.ScreenAvailHeight != nil {
		ah = min(*cfg.ScreenAvailHeight, sh)
	}
	if ah == sh {
		taskbar := map[string]uint32{"windows": 40, "macos": 25, "linux": 27}[targetOS]
		ah = sh - taskbar
	}
	cfg.ScreenAvailWidth, cfg.ScreenAvailHeight = config.Uint32(aw), config.Uint32(ah)
	if cfg.WindowOuterWidth == nil || *cfg.WindowOuterWidth > aw {
		cfg.WindowOuterWidth = config.Uint32(aw)
	}
	if cfg.WindowOuterHeight == nil || *cfg.WindowOuterHeight > ah {
		cfg.WindowOuterHeight = config.Uint32(ah)
	}
}
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd goapi && go test ./pkg/fingerprint/... && go vet ./...`
Expected: `ok`, and vet prints nothing.

- [ ] **Step 5: Commit**: `git commit -am "fix(goapi): size the window inside the sampled screen and always block host voices (#166)"`

### Task 5: `Goto` waits for the main frame within its own timeout (#166.5)

**Files:**
- Modify: `goapi/page.go:78-83` (NewPage) and `:196-216` (Goto)
- Create: `goapi/frame_wait_test.go`

- [ ] **Step 1: Write the failing test**

```go
package camoufox

import (
	"context"
	"sync/atomic"
	"testing"
	"time"
)

// #166: Goto gave up after a fixed 2 s while a loaded browser attached the
// main frame after ~7 s (context 11 of 50, Windows).
func TestWaitMainFrame(t *testing.T) {
	var frame atomic.Value
	frame.Store("")
	get := func() string { return frame.Load().(string) }
	go func() { time.Sleep(300 * time.Millisecond); frame.Store("f1") }()
	if f, err := waitMainFrame(context.Background(), get, 5*time.Second); err != nil || f != "f1" {
		t.Fatalf("late frame: got %q, %v", f, err)
	}
	frame.Store("")
	if _, err := waitMainFrame(context.Background(), get, 100*time.Millisecond); err == nil {
		t.Fatal("no frame: want a timeout error")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := waitMainFrame(ctx, get, time.Second); err != context.Canceled {
		t.Fatalf("cancelled: got %v, want context.Canceled", err)
	}
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd goapi && go test -run TestWaitMainFrame .`
Expected: FAIL (does not compile), with `undefined: waitMainFrame`.

- [ ] **Step 3: Implement**

Add to `goapi/page.go`:

```go
// waitMainFrame returns the main frame id once get reports one, bounded by
// timeout. Under load the browser attaches the frame late (#166).
func waitMainFrame(ctx context.Context, get func() string, timeout time.Duration) (string, error) {
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	tick := time.NewTicker(20 * time.Millisecond)
	defer tick.Stop()
	for {
		if f := get(); f != "" {
			return f, nil
		}
		select {
		case <-tick.C:
		case <-deadline.C:
			return "", fmt.Errorf("camoufox: main frame not attached after %s", timeout)
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
}
```

In `Goto`, move the `opt := GotoOptions{...}` block, including its `if len(opts) > 0` overrides, to the top of the function. Then replace everything from `frame := p.MainFrameID()` through the closing brace of `if frame == "" { ... }` with:

```go
	frame, err := waitMainFrame(ctx, p.MainFrameID, opt.Timeout)
	if err != nil {
		return err
	}
```

If `err` is already declared later in `Goto`, change that later `err :=` to
`err =`. Add `"fmt"` to the imports if it is missing. If `errors` becomes
unused, remove it.

In `NewPage`, replace the 5 s `select`:

```go
	select {
	case <-p.contextReadyCh:
	case <-time.After(30 * time.Second):
		_ = p.Close(ctx)
		return nil, errors.New("camoufox: new page's main execution context never became ready (30s)")
	case <-ctx.Done():
		return nil, ctx.Err()
	}
```

Check that `p.Close(ctx)` exists with that signature
(`grep -n "func (p \*Page) Close" goapi/*.go`). If it has a different
signature, adapt the call.

- [ ] **Step 4: Run it and watch it pass**

Run: `cd goapi && go test -run TestWaitMainFrame . && go vet ./... && CAMOUFOX_BIN=<binary> go test -run 'TestGoto|TestDownloadOnDownload' .`
Expected: PASS.

- [ ] **Step 5: Commit**: `git commit -am "fix(goapi): Goto waits for the main frame within its own timeout; NewPage fails loudly (#166)"`

### Task 6: `FONTCONFIG_FILE` on Linux, generic prefs (#162b, #162 B), and `webrtc_ip` in the e2e driver

**Files:**
- Create: `goapi/fontenv.go`, `goapi/fontenv_test.go`
- Modify: `goapi/launch.go` (env builder at `:167-172`, prefs map after the `systemUIFont` block)
- Modify: `goapi/cmd/e2edriver/main.go` (`args` struct, `launch` case), `e2e/drivers/go.py:77-83`
- Modify: `pythonlib/camoufox/utils.py:315`, to correct the false comment

**Interfaces:**
- Produces: `genericFontPrefs(targetOS string) map[string]string` and
  `spoofedOS(platform string) string` in package `camoufox`. W4 Task 16 adds
  `font.name-list.emoji` to the same table.
- The table must match pythonlib's `GENERIC_FONT_FAMILIES` (Task 7) exactly.

- [ ] **Step 1: Write the failing tests**

```go
package camoufox

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGenericFontPrefsNameOnlyFamiliesTheSpoofedOSShips(t *testing.T) {
	raw, err := os.ReadFile("pkg/fingerprint/data/fonts.json")
	if err != nil {
		t.Fatal(err)
	}
	var lists map[string][]string
	if err := json.Unmarshal(raw, &lists); err != nil {
		t.Fatal(err)
	}
	key := map[string]string{"windows": "win", "macos": "mac", "linux": "lin"}
	for osName, k := range key {
		ships := map[string]bool{}
		for _, f := range lists[k] {
			ships[f] = true
		}
		prefs := genericFontPrefs(osName)
		if len(prefs) == 0 {
			t.Fatalf("%s: no generic prefs", osName)
		}
		for pref, v := range prefs {
			for _, fam := range strings.Split(v, ",") {
				if fam = strings.TrimSpace(fam); !ships[fam] {
					t.Errorf("%s %s names %q, which %s's font list does not ship", osName, pref, fam, osName)
				}
			}
		}
	}
}

func TestLinuxFontconfigPointsAtTheBundleForTheSpoofedOS(t *testing.T) {
	bundle := t.TempDir()
	conf := filepath.Join(bundle, "fontconfig", "windows")
	if err := os.MkdirAll(conf, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(conf, "fonts.conf"), []byte(`<fontconfig><dir prefix="cwd">fonts</dir></fontconfig>`), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("HOME", t.TempDir())
	out, err := linuxFontconfig(filepath.Join(bundle, "camoufox-bin"), "windows")
	if err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(out)
	if !strings.Contains(string(got), "<dir>"+filepath.Join(bundle, "fonts")+"</dir>") || strings.Contains(string(got), `prefix="cwd"`) {
		t.Fatalf("runtime conf %s = %s", out, got)
	}
	if _, err := linuxFontconfig(filepath.Join(bundle, "camoufox-bin"), "macos"); err == nil {
		t.Fatal("a missing conf must be an error the caller can report")
	}
}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd goapi && go test -run 'TestGenericFontPrefs|TestLinuxFontconfig' .`
Expected: FAIL (does not compile), with `undefined: genericFontPrefs`.

- [ ] **Step 3: Implement `goapi/fontenv.go`**

```go
package camoufox

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// genericFamilies names each spoofed OS's generics: monospace, serif,
// sans-serif. Without these, generics resolve through the HOST's
// font.name-list.* prefs (Menlo on a mac host, Consolas on a Windows host),
// which the launch font mask refuses, so monospace fell to the first allowed
// family: Arial or Arimo (#162). Every family must be in that OS's fonts.json
// (TestGenericFontPrefsNameOnlyFamiliesTheSpoofedOSShips). Kept identical to
// pythonlib's GENERIC_FONT_FAMILIES.
// ponytail: x-western and x-unicode only; other lang groups keep the host
// default until the browser-side fix (#162, W1) lands.
var genericFamilies = map[string][3]string{
	"windows": {"Consolas, Courier New", "Times New Roman", "Arial"},
	"macos":   {"Menlo, Courier New", "Times", "Helvetica"},
	"linux":   {"Cousine", "Tinos", "Arimo"},
}

func genericFontPrefs(targetOS string) map[string]string {
	f, ok := genericFamilies[targetOS]
	if !ok {
		return nil
	}
	out := map[string]string{}
	for _, lang := range []string{"x-western", "x-unicode"} {
		out["font.name-list.monospace."+lang] = f[0]
		out["font.name-list.serif."+lang] = f[1]
		out["font.name-list.sans-serif."+lang] = f[2]
	}
	return out
}

// spoofedOS maps navigator.platform to the bundle's OS directory names.
func spoofedOS(platform string) string {
	switch {
	case strings.Contains(platform, "Win"):
		return "windows"
	case strings.Contains(platform, "Mac"):
		return "macos"
	case strings.Contains(strings.ToLower(platform), "linux"):
		return "linux"
	}
	return ""
}

// linuxFontconfig mirrors pythonlib get_env_vars and _generate_fontconfig
// (pythonlib/camoufox/utils.py:58-92, :303-332). On a Linux host, fontconfig is
// pointed at the bundle's conf for the SPOOFED OS, with its relative fonts
// dir made absolute. Without it, generics resolve against the host's system
// fontconfig (#162). The file name matches pythonlib's
// (fonts-<sha256[:12]>.conf), so the two launchers share one cache entry.
func linuxFontconfig(executablePath, targetOS string) (string, error) {
	bundle := filepath.Dir(executablePath)
	var src []byte
	var err error
	for _, dir := range []string{"fontconfig", "fontconfigs"} {
		if src, err = os.ReadFile(filepath.Join(bundle, dir, targetOS, "fonts.conf")); err == nil {
			break
		}
	}
	if err != nil {
		return "", fmt.Errorf("camoufox: no fontconfig/%s/fonts.conf beside %s: %w", targetOS, executablePath, err)
	}
	conf := strings.ReplaceAll(string(src), `<dir prefix="cwd">fonts</dir>`, "<dir>"+filepath.Join(bundle, "fonts")+"</dir>")
	cache, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(cache, "camoufox", "fontconfig")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	sum := sha256.Sum256([]byte(conf))
	out := filepath.Join(dir, fmt.Sprintf("fonts-%x.conf", sum[:6]))
	if _, err := os.Stat(out); err != nil {
		if err := os.WriteFile(out, []byte(conf), 0o644); err != nil {
			return "", err
		}
	}
	return out, nil
}
```

- [ ] **Step 4: Wire it into `launch.go`**

After `env = append(env, envVars...)`, add:

```go
	if config.HostOS() == "linux" {
		if fc, err := linuxFontconfig(lc.executablePath, spoofedOS(cfg.NavigatorPlatform)); err == nil {
			env = append(env, "FONTCONFIG_FILE="+fc)
		} else {
			// A dev build (dist/bin) has no bundle beside it; say so rather than
			// failing a launch that used to work. pythonlib raises here instead.
			fmt.Fprintf(os.Stderr, "camoufox: %v; generics resolve against the host's fontconfig\n", err)
		}
	}
```

After the `systemUIFont` block in the prefs map, add:

```go
	// #162: see genericFamilies. CAMOUFOX_NO_GENERIC_PREFS=1 is a test hook, so
	// the browser-side fix can be measured without these prefs hiding it.
	if os.Getenv("CAMOUFOX_NO_GENERIC_PREFS") != "1" {
		for k, v := range genericFontPrefs(spoofedOS(cfg.NavigatorPlatform)) {
			prefs[k] = v
		}
	}
```

The caller's `lc.firefoxUserPrefs` must still win. Check that it is merged
after this point (`grep -n firefoxUserPrefs goapi/launch.go`).

In `pythonlib/camoufox/utils.py:315`, change the comment
`# v150+ uses "fontconfig/" (matching the Go launcher); older bundles shipped "fontconfigs/".`
to `# v150+ uses "fontconfig/"; older bundles shipped "fontconfigs/". goapi's linuxFontconfig mirrors this.`

- [ ] **Step 5: `webrtc_ip` through the e2e driver**

In `goapi/cmd/e2edriver/main.go`, add `WebRTCIP string `json:"webrtc_ip"`` to
`args`. In the `launch` case, before `camoufox.Launch`, add:

```go
		if a.WebRTCIP != "" {
			// What geoip= sets: launch-level webrtc:ipv4 (#163).
			opts = append(opts, camoufox.WithConfig(&config.Config{WebRTCIPv4: a.WebRTCIP}))
		}
```

Also import `github.com/lang315/camoufox/goapi/pkg/config`.

In `e2e/drivers/go.py`, remove `("webrtc_ip", webrtc_ip)` from the skip tuple
and pass `webrtc_ip=webrtc_ip or ""` in `self.rpc("launch", ...)`.

- [ ] **Step 6: Run everything**

Run: `cd goapi && go test ./... && go vet ./... && cd ../e2e && python3 -m pytest -q -p no:cacheprovider drivers oracle`
Expected: PASS. The integration tests skip without `CAMOUFOX_BIN`; run them
once with it set.

- [ ] **Step 7: Commit**: `git commit -am "fix(goapi): spoofed-OS fontconfig on Linux, generic font prefs, webrtc_ip in the e2e driver (#162, #163)"`

### Task 7: The W2 e2e dispatch and ledger

**Files:** `e2e/known.py`

- [ ] **Step 1:** Push the branch, and open a PR against #166 and #162 carrying
  the test outputs.
- [ ] **Step 2:** Dispatch `gh workflow run e2e.yml --repo lang315/camoufox --ref fix/166-goapi -f release=v152.0.4-beta.31-fork.1`.
  Watch it in the background.
- [ ] **Step 3: Read each host's `KNOWN`, `FIXED?` and `FAILED` lines, and update `known.py` to match what was measured:**
  - **Expect `FIXED?`, then delete:**
    - The `test_upload_and_download[go]` RAISES entry.
    - The Windows `go-linux` `voices_no_foreign_os` entry.
    - The Linux `test_fingerprint_is_coherent[go-` #162 entries. These need
      a Linux leg; see Step 4.
  - **Expect green for 3 dispatches, then delete** the non-strict go #166
    `screen_contains_viewport` entry.
  - **Also expect `FIXED?` from goapi's generic prefs (B):**
    - The Windows #162 `(pkg|pw|go)-(macos|linux)` entries, for `go` only.
      Split the regex so pkg and pw keep their entry until W3.
    - The Darwin non-strict #162 entry, for `go`. Wait for 3 greens.
  - **Expect new reds:** `test_webrtc_does_not_reveal_lan_address[go]` now
    runs, and leaks until W1. Add it to the existing #163 entries by widening
    their regex from `\[(pkg|pw)\]` to `\[(pkg|pw|go)\]`, strict, on every
    host where it was measured red.
- [ ] **Step 4: The Linux leg.** The fork.1 release has no Linux asset. Use the PR
  gate's e2e job, which builds Linux, as the Linux measurement.
- [ ] **Step 5:** Commit the ledger, run the gate plus one more dispatch, then merge.

---

## W3: pythonlib (no browser build)

Branch `fix/164-pythonlib` from `main`.

### Task 8: Generic font prefs (#162 B)

**Files:**
- Modify: `pythonlib/camoufox/utils.py` (constant near `_WINDOW_DIM_KEYS`, and the call in `launch_options` after the fonts block at `:1252-1266`)
- Create: `pythonlib/tests/test_generic_font_prefs.py`

- [ ] **Step 1: Write the failing test**

```python
"""#162 (B): name the spoofed OS's generic families in prefs."""

import os
import sys

import orjson
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from camoufox import utils  # noqa: E402
from test_launch_geometry import host  # noqa: E402

FONTS = orjson.loads(open(os.path.join(os.path.dirname(utils.__file__), "fonts.json"), "rb").read())


@pytest.mark.parametrize("os_key", ["win", "mac", "lin"])
def test_every_named_family_ships_in_that_os_list(os_key):
    for pref, value in utils.generic_font_prefs(os_key).items():
        for fam in (f.strip() for f in value.split(",")):
            assert fam in FONTS[os_key], f"{os_key} {pref} names {fam!r}, which {os_key}'s list lacks"


@pytest.mark.parametrize("spoof,mono", [("windows", "Consolas, Courier New"), ("macos", "Menlo, Courier New"), ("linux", "Cousine")])
def test_launch_options_sets_the_spoofed_generics(spoof, mono):
    with host(None):
        prefs = utils.launch_options(os=spoof, i_know_what_im_doing=True)["firefox_user_prefs"]
    assert prefs["font.name-list.monospace.x-western"] == mono


def test_the_test_hook_turns_them_off(monkeypatch):
    monkeypatch.setenv("CAMOUFOX_NO_GENERIC_PREFS", "1")
    with host(None):
        prefs = utils.launch_options(os="windows", i_know_what_im_doing=True)["firefox_user_prefs"]
    assert not any(k.startswith("font.name-list.") for k in prefs)


def test_a_caller_pref_wins():
    with host(None):
        prefs = utils.launch_options(os="windows", i_know_what_im_doing=True,
                                     firefox_user_prefs={"font.name-list.monospace.x-western": "Courier New"})["firefox_user_prefs"]
    assert prefs["font.name-list.monospace.x-western"] == "Courier New"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd pythonlib && python3 -m pytest -q tests/test_generic_font_prefs.py`
Expected: FAIL with `AttributeError: module 'camoufox.utils' has no attribute 'generic_font_prefs'`.

- [ ] **Step 3: Implement.** Add near `_WINDOW_DIM_KEYS`:

```python
# #162 (B): each spoofed OS's generics (monospace, serif, sans-serif). Without
# them, generics resolve through the HOST's font.name-list.* prefs (Menlo on a
# mac host, Consolas on a Windows host), which the launch font mask refuses, so
# monospace fell to the first allowed family: Arial or Arimo. Every family is
# in that OS's fonts.json (tests/test_generic_font_prefs.py). Kept identical to
# goapi's genericFamilies (goapi/fontenv.go).
# ponytail: x-western and x-unicode only; other lang groups keep the host
# default until the browser-side fix (W1) lands.
GENERIC_FONT_FAMILIES = {
    'win': ('Consolas, Courier New', 'Times New Roman', 'Arial'),
    'mac': ('Menlo, Courier New', 'Times', 'Helvetica'),
    'lin': ('Cousine', 'Tinos', 'Arimo'),
}


def generic_font_prefs(target_os: str) -> Dict[str, str]:
    families = GENERIC_FONT_FAMILIES.get(target_os)
    if not families:
        return {}
    prefs = {}
    for lang in ('x-western', 'x-unicode'):
        for generic, value in zip(('monospace', 'serif', 'sans-serif'), families):
            prefs[f'font.name-list.{generic}.{lang}'] = value
    return prefs
```

In `launch_options`, right after the `elif 'fonts' not in config ...` block, add:

```python
    # CAMOUFOX_NO_GENERIC_PREFS=1 is a test hook: it lets the browser-side #162
    # fix be measured without these prefs hiding it.
    if environ.get('CAMOUFOX_NO_GENERIC_PREFS') != '1':
        for key, value in generic_font_prefs(target_os).items():
            firefox_user_prefs.setdefault(key, value)
```

Confirm that `target_os` is bound at that point, with a value of `'win'`,
`'mac'` or `'lin'` (`grep -n "target_os =" pythonlib/camoufox/utils.py`).

- [ ] **Step 4: Run it and watch it pass**

Run: `cd pythonlib && python3 -m pytest -q tests/test_generic_font_prefs.py tests/test_launch_geometry.py tests/test_launch_environment.py`
Expected: PASS.

- [ ] **Step 5: Commit**: `git commit -am "fix(pythonlib): name the spoofed OS's generic fonts in prefs (#162)"`

### Task 9: No more `setWebRTCIPv4("")` (#163, pythonlib half)

**Files:** `pythonlib/camoufox/fingerprints.py:1071-1074`, and `pythonlib/tests/test_webrtc_ipv6_spoofing.py` (extend it)

- [ ] **Step 1: Write the failing test** (append to `test_webrtc_ipv6_spoofing.py`):

```python
def test_no_webrtc_ip_emits_no_setter():
    # An empty stored value switched spoofing on with "" and hid the launch-level
    # webrtc:ipv4 that geoip= sets (#163).
    from camoufox.fingerprints import generate_context_fingerprint
    script = generate_context_fingerprint(os="windows")["init_script"]
    assert "setWebRTCIPv4" not in script and "setWebRTCIPv6" not in script
```

- [ ] **Step 2: Run it:** `cd pythonlib && python3 -m pytest -q tests/test_webrtc_ipv6_spoofing.py -k no_webrtc_ip`. It fails, because `setWebRTCIPv4("")` is present.
- [ ] **Step 3: Implement:** delete the `else:` branch that appends `w.setWebRTCIPv4("")`.
- [ ] **Step 4: Run:** `cd pythonlib && python3 -m pytest -q tests/test_webrtc_ipv6_spoofing.py`. It passes.
- [ ] **Step 5: Commit**: `git commit -am "fix(pythonlib): NewContext without webrtc_ip sets no WebRTC IP (#163)"`

### Task 10: A context's geometry stays inside the launch window (#164a)

**Files:**
- Modify: `pythonlib/camoufox/utils.py` (new `attach_launch_window` beside `attach_launch_fonts`)
- Modify: `pythonlib/camoufox/sync_api.py:133` and `pythonlib/camoufox/async_api.py:137` (call it); `NewContext` and `AsyncNewContext` (pass it through)
- Modify: `pythonlib/camoufox/fingerprints.py` (`generate_context_fingerprint`: new `launch_window` parameter, screen clamp, and viewport)
- Create: `pythonlib/tests/test_context_geometry.py`

**Interfaces:**
- Produces: `browser._camoufox_launch_window = {'outer': (w, h), 'inner': (w or None, h or None), 'screen': (w, h)}`.
- Produces: `generate_context_fingerprint(..., launch_window: Optional[Dict] = None)`.

- [ ] **Step 1: Write the failing test**

```python
"""#164: NewContext's geometry must fit the launch window, which is process-wide."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from camoufox.fingerprints import generate_context_fingerprint  # noqa: E402

LW = {"outer": (1366, 728), "inner": (1366, 643), "screen": (1366, 768)}


def test_viewport_is_the_launch_inner_and_the_screen_holds_the_window():
    for _ in range(200):
        fp = generate_context_fingerprint(os="windows", launch_window=LW)
        vp = fp["context_options"]["viewport"]
        assert (vp["width"], vp["height"]) == LW["inner"]
        sw, sh = fp["config"]["screen.width"], fp["config"]["screen.height"]
        assert sw >= LW["outer"][0] and sh >= LW["outer"][1], (sw, sh)
        assert f"setScreenDimensions({sw}, {sh})" in fp["init_script"].replace(" ", "").replace(",", ", ")


def test_no_launch_inner_means_no_viewport_and_no_scale_factor():
    lw = {**LW, "inner": (None, None)}
    opts = generate_context_fingerprint(os="macos", launch_window=lw)["context_options"]
    assert opts.get("no_viewport") is True
    assert "viewport" not in opts and "device_scale_factor" not in opts
```

Before relying on the exact call text, check how `_build_init_script` renders
`setScreenDimensions` (`grep -n setScreenDimensions pythonlib/camoufox/fingerprints.py`).
Adjust the third assertion to match that rendering, without normalising
whitespace.

- [ ] **Step 2: Run it:** `cd pythonlib && python3 -m pytest -q tests/test_context_geometry.py`. It fails with `unexpected keyword argument 'launch_window'`.
- [ ] **Step 3: Implement.** In `utils.py`, beside `attach_launch_fonts`, add:

```python
def attach_launch_window(target: Any, from_options: Optional[Dict[str, Any]]) -> Any:
    """Record the launch window and screen on the browser for NewContext (#164).

    window.outerWidth/Height come from the process-wide MaskConfig, so every
    context shares the launch window; a context can only claim a viewport inside
    it and a screen that holds it. 1280x1040 is browser-init.patch's default
    when the config sets no outer size.
    """
    cfg = _reassemble_camou_config(from_options) or {}
    try:
        target._camoufox_launch_window = {
            'outer': (cfg.get('window.outerWidth') or 1280, cfg.get('window.outerHeight') or 1040),
            'inner': (cfg.get('window.innerWidth'), cfg.get('window.innerHeight')),
            'screen': (cfg.get('screen.width'), cfg.get('screen.height')),
        }
    except AttributeError:
        pass  # a Playwright object that does not accept attributes
    return target
```

Import it in `sync_api.py` and `async_api.py` beside `attach_launch_fonts`, and
call `attach_launch_window(browser, from_options)` on the line after each
`attach_launch_fonts(browser, from_options)`. In `NewContext`, pass
`launch_window=getattr(browser, '_camoufox_launch_window', None)` to
`generate_context_fingerprint`. Do the same in `AsyncNewContext`'s lambda.

In `fingerprints.py`:
1. Add `launch_window: Optional[Dict[str, Any]] = None` to
   `generate_context_fingerprint`'s signature, and document it in the
   docstring's Parameters list.
2. Just before `# Inject explicit timezone/locale into config`, add:

```python
    # #164: the launch window is process-wide, so a context's screen must hold
    # it. When the drawn screen cannot, claim the launch's own screen, which
    # launch_options already made hold the window.
    if launch_window:
        ow, oh = launch_window['outer']
        sw0, sh0 = screen.get('width'), screen.get('height')
        lsw, lsh = launch_window['screen']
        if not (sw0 and sh0 and sw0 >= ow and sh0 >= oh) and lsw and lsh:
            screen = {**screen, 'width': lsw, 'height': lsh}
            config['screen.width'], config['screen.height'] = lsw, lsh
```

3. Replace the `if sw and sh: context_options['viewport'] = {...}` block, and the
   `dpr` block after it, with:

```python
    if sw and sh:
        inner = (launch_window or {}).get('inner') or (None, None)
        if all(inner):
            # The launch window's own inner size: inner <= outer by construction.
            context_options['viewport'] = {'width': inner[0], 'height': inner[1]}
        elif launch_window:
            context_options['no_viewport'] = True
        else:
            # ponytail: a browser NewBrowser did not launch carries no record, so the
            # old preset-sized viewport stays and #164 can still happen there.
            context_options['viewport'] = {'width': sw, 'height': max(sh - 28, 600)}
    dpr = screen.get('devicePixelRatio')
    # Playwright rejects deviceScaleFactor with a null viewport.
    if dpr and not context_options.get('no_viewport'):
        context_options['device_scale_factor'] = dpr
```

Make sure `sw`/`sh` are read from the possibly replaced `screen`. The existing
`sw = screen.get('width')` sits after the new block, so it already is.

- [ ] **Step 4: Run:** `cd pythonlib && python3 -m pytest -q tests/test_context_geometry.py tests/test_viewport_default.py tests/test_fingerprint_fixes.py`. It passes.
- [ ] **Step 5: Commit**: `git commit -am "fix(pythonlib): NewContext keeps inner <= outer <= screen against the launch window (#164)"`

### Task 11: Bare Playwright is told about `no_viewport` (#164b)

**Files:** `README.md`, `pythonlib/README.md`, and `e2e/drivers/playwright_drivers.py:74-88,128-145`

- [ ] **Step 1:** In both READMEs, find the section that shows `launch_options`
  used with bare Playwright (`grep -n launch_options README.md pythonlib/README.md`).
  Add this after it:

```markdown
> **Open contexts with `no_viewport=True`.** Playwright's default viewport is 1280x720 whatever
> window the fingerprint spoofs, so a spoofed window smaller than that gives a page
> `innerWidth > outerWidth`, which no real browser can report (#164). `NewBrowser` and
> `Camoufox()` default to it for you:
>
> ```python
> browser = playwright.firefox.launch(**launch_options(os="macos"))
> page = browser.new_context(no_viewport=True).new_page()
> ```
```

- [ ] **Step 2:** In the e2e drivers, follow the README:
  - `PwBrowser.__init__(self, browser, identity_context=None, context_kwargs=None)`
    stores `self._ctx_kwargs = context_kwargs or {}`.
  - `new_context` returns `PwCtx(self.b.new_context(**self._ctx_kwargs))`.
  - `PwDriver.launch` builds `PwBrowser(playwright().firefox.launch(**opts), context_kwargs={"no_viewport": True})`.
- [ ] **Step 3:** In `e2e/known.py`, delete the `pw-` #164 entry, "Bare
  Playwright's default 1280x720 viewport", from Darwin and Linux. The PR body
  says why: the documented path changed, and the suite measures the
  documented path.
- [ ] **Step 4:** Run `cd e2e && python3 -m pytest -q -p no:cacheprovider --binary=<local fork.1 binary> --drivers=pw journeys/test_02_fingerprint.py`. It passes, and no `KNOWN #164` appears for pw.
- [ ] **Step 5: Commit**: `git commit -am "docs, e2e: bare Playwright opens contexts with no_viewport=True (#164)"`

### Task 12: The W3 dispatch and ledger

- [ ] **Step 1:** PR against #162, #163 and #164, then dispatch `e2e.yml` on the branch.
- [ ] **Step 2: Read the ledger results:**
  - **pkg and pw #162 entries** (strict on Windows, non-strict on Darwin) are
    expected to report `FIXED?` on the released binary. That is B working.
  - **Delete the entries that do.** For the non-strict Darwin entry, wait
    for 3 greens.
  - **pkg #164 `test_new_context_fingerprint_is_coherent`** is non-strict:
    3 greens on each host, then delete.
- [ ] **Step 3:** Commit the ledger, run the gate, then merge.

---

## W1: browser (one build)

Branch `fix/163-162-browser` from `main`, after W2 and W3 have merged. That
way the flag from Task 8 and the go webrtc test from Task 6 exist.

### Task 13: The RED-first guard for #162 (A)

**Files:** Create `tests/patches/generic-monospace-launch-mask.py`

- [ ] **Step 1: Write the guard**

```python
"""
Guard for #162 (A): under a LAUNCH-level font list, CSS `monospace` stays monospaced.

Launches the raw binary with CAMOU_CONFIG holding only a `fonts` list, with no
font.name-list.* prefs (pythonlib's and goapi's #162 prefs would hide the
browser-side fix) and no FONTCONFIG_FILE. So generics start from the HOST's
default monospace, which the list is built to refuse.

What it can see: Linux hosts only (it builds the list from fc-list/fc-match).
What it cannot see: DWrite and CoreText. The e2e dispatch with
CAMOUFOX_NO_GENERIC_PREFS=1 is the macOS and Windows evidence.

PASS: `monospace` i-width == m-width, while `sans-serif` i != m (negative control).
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# The candidate row the patch walks for monospace (font-list-spoofing.patch).
MONO_ROW = ["Menlo", "Monaco", "Consolas", "Courier New", "Courier", "Cousine",
            "Liberation Mono", "DejaVu Sans Mono", "Noto Sans Mono"]
PROBE = """(() => { const x = document.createElement('canvas').getContext('2d');
  const w = (f, s) => { x.font = '32px ' + f; return x.measureText(s).width; };
  return {mono: [w('monospace', 'iiiiiiiiii'), w('monospace', 'mmmmmmmmmm')],
          sans: [w('sans-serif', 'iiiiiiiiii'), w('sans-serif', 'mmmmmmmmmm')]}; })()"""


def fc(*args):
    return subprocess.run(["fc-" + args[0], *args[1:]], capture_output=True, text=True, check=True).stdout


def build_list():
    host_mono = fc("match", "-f", "%{family[0]}", "monospace").strip()
    installed = set(l.strip() for l in fc("list", ":", "family").replace(",", "\n").splitlines())
    row_family = next((f for f in MONO_ROW if f in installed and f != host_mono), None)
    sans = next((f for f in ["DejaVu Sans", "Liberation Sans", "Noto Sans", "Arimo"] if f in installed), None)
    return host_mono, row_family, sans


async def main() -> int:
    if platform.system() != "Linux":
        print("SKIP: this guard reads the host font universe through fontconfig (Linux only)")
        return 0
    host_mono, row_family, sans = build_list()
    print(f"host default monospace: {host_mono!r}; row family allowed: {row_family!r}; sans: {sans!r}")
    if not row_family or not sans:
        print("FAIL: cannot build a list that refuses the host monospace but allows a row family")
        return 1
    from playwright.async_api import async_playwright
    exe = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
    env = {k: v for k, v in os.environ.items() if k != "FONTCONFIG_FILE"}
    env["CAMOU_CONFIG_1"] = json.dumps({"fonts": [row_family, sans]})
    async with async_playwright() as p:
        b = await p.firefox.launch(executable_path=exe, headless=True, env=env)
        page = await b.new_page()
        await page.goto("about:blank")
        r = await page.evaluate(PROBE)
        await b.close()
    print(f"monospace i/m {r['mono']}; sans-serif i/m {r['sans']}")
    if r["sans"][0] == r["sans"][1]:
        print("FAIL: negative control did not go red (sans-serif is monospaced), so the probe is VACUOUS")
        return 1
    if r["mono"][0] != r["mono"][1]:
        print("FAIL: #162 monospace collapsed to a proportional face under a launch-only list")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Prove it is RED on `main`'s build.** Take the Linux artifact of
  the latest green `tests.yml` run on `main`:
  `gh run download <run> --repo lang315/camoufox -n CamoufoxBuilds-linux-x86_64`.
  Then run `CAMOUFOX_EXECUTABLE_PATH=<bin> python3 tests/patches/generic-monospace-launch-mask.py`
  on a Linux machine (buildpc WSL, or dispatch `smoke.yml`).
  - **Expected:** `FAIL: #162 monospace collapsed`, with the negative control
    passing.
  - **Record:** the run id, its build, and its branch (lesson 9).
  - **If it passes instead:** the premise is wrong on this host. Stop, and
    report it on #162.
- [ ] **Step 3: Commit**: `git commit -m "test(patches): #162 guard, monospace under a launch-only font list"`

### Task 14: The launch-level WebRTC IP fallback (#163)

**Files:** Create `patches/webrtc-launch-ip-fallback.patch`. Its basename sorts
after `webrtc-ip-spoofing2.patch`, which `scripts/_mixin.py:80` confirms.

- [ ] **Step 1: Check the premise in the tree.**
  - Run `make dir`, or reuse an existing prepared tree.
  - Confirm that `dom/base/WebRTCIPManager.cpp` already includes
    `MaskConfig.hpp` (added by `webrtc-ip-spoofing2.patch`).
  - Confirm that `GetIPv4` and `GetIPv6` read storage only.
  - Confirm that the process which calls `ShouldSpoofCandidateIP` already
    reads `MaskConfig` for `webrtc:localipv4`. Read the callers:
    `grep -n "ShouldSpoofCandidateIP\|GetLocalIPv4" camoufox-*/dom/media/webrtc -r`.
- [ ] **Step 2: Edit through the workspace.** Run `make edits`, choose "Reset
  workspace", then edit `dom/base/WebRTCIPManager.cpp`. Replace the two
  getters with:

```cpp
/* static */ bool
WebRTCIPManager::GetIPv4(uint32_t userContextId, nsAString& outIPv4) {
  // A per-context value wins, but an empty one means "not set": NewContext used
  // to store "" for a context without webrtc_ip, and it must not hide the
  // launch-level value (#163).
  nsString key = IPv4KeyForUserContext(userContextId);
  if (RoverfoxStorageManager::GetString(key, outIPv4) && !outIPv4.IsEmpty()) {
    return true;
  }
  // Launch-level webrtc:ipv4 -- what geoip= sets. Not written back to storage,
  // so a later per-context setWebRTCIPv4 still wins (TimezoneManager does write
  // back; WebRTC must not, because the per-context setter self-disables).
  if (auto v = MaskConfig::GetString("webrtc:ipv4")) {
    outIPv4.AssignASCII(v.value().c_str());
    return !outIPv4.IsEmpty();
  }
  outIPv4.Truncate();
  return false;
}
```

  `GetIPv6` is identical, with `IPv6KeyForUserContext` and `"webrtc:ipv6"`.
  Then choose "Write workspace to patch" and name it
  `webrtc-launch-ip-fallback.patch`.
- [ ] **Step 3: Check the new patch** with `git diff --stat` on the tree. It
  must touch `dom/base/WebRTCIPManager.cpp` only. Then run
  `patch -p1 --forward -l --binary --dry-run < ../patches/webrtc-launch-ip-fallback.patch`
  on a tree where `webrtc-ip-spoofing2.patch` is applied and this one is not.
  Expected: it applies with no fuzz and no offsets beyond what is printed.
- [ ] **Step 4: Add the must-not-change case** to `e2e/journeys/test_03_network.py`,
  plus driver support:

```python
CONTEXT_WEBRTC_IP = "198.51.100.9"  # TEST-NET-2


def test_context_webrtc_ip_overrides_the_launch_one(drv, site, stun, check):
    lan = lan_ips()
    if not lan:
        pytest.skip("this host has no non-loopback IPv4 address to leak")
    b = drv.launch(os="windows", webrtc_ip=SPOOFED_WEBRTC_IP)
    page = b.new_identity_context(webrtc_ip=CONTEXT_WEBRTC_IP).new_page()
    page.goto(site.url(f"/webrtc?stun={sorted(lan)[0]}:{stun.port}"))
    got = wait_out(page, 20)
    b.close()
    text = " ".join(got["candidates"]) + got["sdp"]
    check(stun.seen, f"the STUN server was asked (non-vacuous); {len(got['candidates'])} candidates")
    check(CONTEXT_WEBRTC_IP in text, f"the context's WebRTC IP appears: {got['candidates']}")
    check(SPOOFED_WEBRTC_IP not in text, "the launch-level WebRTC IP does not")
    check.done()
```

  In `e2e/drivers/playwright_drivers.py`:
  - `PwBrowser.new_identity_context(self, **kw)` calls `self._identity_context(self.b, **kw)`.
  - `PkgDriver` builds its lambda as
    `lambda br, webrtc_ip=None: NewContext(br, os=os, webrtc_ip=webrtc_ip or launch_webrtc_ip)`,
    where `launch_webrtc_ip = webrtc_ip` is bound before the lambda.

  Run it now on the fork.1 release (`--drivers=pkg`). It must PASS already,
  because the per-context path works today. That is the "must not change"
  baseline.
- [ ] **Step 5: Commit**: `git commit -m "fix(webrtc): fall back to launch-level webrtc:ipv4/ipv6 when a context set none (#163)"`

### Task 15: The generic table serves a launch-only mask (#162 A)

**Files:** `patches/font-list-spoofing.patch`, edited at its own position (#131)

- [ ] **Step 1: Enumerate before editing (lessons 5 and 7).** List every site that
  gates on `HasFontList` for generics:
  `grep -n "HasFontList(camouCtx)" patches/font-list-spoofing.patch`.
  Expect three: inside `CamouGenericCandidate` (around `:596`), in
  `gfxFcPlatformFontList::FindGenericFamilies` (around `:353`) and in
  `gfxPlatformFontList::AddGenericFonts` (around `:1024`). Also grep
  `gfxDWriteFontList` and `gfxMacPlatformFontList` in the prepared tree for a
  generic override that answers first. Write the list into the PR body.
- [ ] **Step 2: Rebuild the tree at the patch's position.**
  - Reset to `unpatched`.
  - Apply the patches before `font-list-spoofing.patch` in `list_patches()`
    order, then run `git tag -f first-checkpoint`.
  - Apply `font-list-spoofing.patch`.
  - **Prove the baseline:** regenerate it with `git add -A && git diff first-checkpoint`.
    The result must be byte-identical to `patches/font-list-spoofing.patch`,
    apart from the `index` lines. **Stop if it is not.**
- [ ] **Step 3: Edit all three sites to the same condition.**

```cpp
  const uint32_t camouCtx = mozilla::dom::FontListManager::GetCurrentContext();
  // #162: a launch-only font mask needs the table as much as a per-context list:
  // without it the generic resolves through the HOST's font.name-list pref,
  // which that mask refuses when the spoofed OS differs from the host. With no
  // launch list either, MaskedFontListAppliesTo is false and upstream behaviour
  // -- the context-0 fail-open of CLAUDE.md lesson 5 -- is unchanged.
  const bool camouOwnList =
      camouCtx != 0 && mozilla::dom::FontListManager::HasFontList(camouCtx);
  if (camouOwnList || MaskedFontListAppliesTo(aFontVisibilityProvider)) {
```

  - **`CamouGenericCandidate`:** the condition is inverted:
    `if (!camouOwnList && !MaskedFontListAppliesTo(aFontVisibilityProvider)) { return false; }`.
  - **The two callers:** the existing `if (camouCtx != 0 && HasFontList(camouCtx)) {`
    becomes the form above.
  - **Provider check:** confirm that `aFontVisibilityProvider` is the name in
    scope at each site. `FindGenericFamilies` may name it differently; use its
    name.
  - **`CamouIsFamilyAllowed`:** leave it unchanged. It already asks
    `MaskedFontListBlocks` before `CamouIsFontAllowed`.
- [ ] **Step 4: Regenerate and dry-run.**
  - Regenerate with `git add -A && git diff first-checkpoint > ../patches/font-list-spoofing.patch`.
    Stage new files first, per memory.
  - Re-apply every later patch in order, with `patch --dry-run`, and check
    for no `.rej` or fuzz.
  - Balance the context lines of the new hunks.
- [ ] **Step 5: Commit**: `git commit -m "fix(fonts): the generic table serves a launch-only font mask (#162)"`

### Task 16: SOCKS5 credentials in Juggler (#166.3)

**Files:** `additions/juggler/NetworkObserver.js:629-638`

- [ ] **Step 1: Implement**. Replace the `proxyFilter.onProxyFilterResult(protocolProxyService.newProxyInfo(...))` call with:

```js
        // SOCKS credentials travel in the proxy info itself; promptAuth only ever
        // answers HTTP AUTH_PROXY. Dropping them made an authenticated SOCKS5
        // proxy refuse the connection (NS_ERROR_CONNECTION_REFUSED, #166).
        const socksAuth = proxy.type.startsWith('socks') && proxy.username;
        proxyFilter.onProxyFilterResult(socksAuth ?
          protocolProxyService.newProxyInfoWithAuth(
              proxy.type, proxy.host, proxy.port,
              proxy.username, proxy.password || '',
              '', /* aProxyAuthorizationHeader */
              '', /* aConnectionIsolationKey */
              Ci.nsIProxyInfo.TRANSPARENT_PROXY_RESOLVES_HOST,
              UINT32_MAX, null) :
          protocolProxyService.newProxyInfo(
              proxy.type,
              proxy.host,
              proxy.port,
              '', /* aProxyAuthorizationHeader */
              '', /* aConnectionIsolationKey */
              Ci.nsIProxyInfo.TRANSPARENT_PROXY_RESOLVES_HOST, /* aFlags */
              UINT32_MAX, /* aFailoverTimeout */
              null, /* failover proxy */
          ));
```

  `newProxyInfoWithAuth` accepts only `socks` and `socks4` for credentials
  (`nsProtocolProxyService.cpp:1693`). goapi sends `socks`
  (`goapi/pkg/proxy/proxy.go:137-149`).
- [ ] **Step 2: Commit**: `git commit -m "fix(juggler): pass SOCKS credentials to the proxy info (#166)"`

### Task 17: The W1 build, and its evidence

- [ ] **Step 1:** Push, then dispatch `gh workflow run build.yml --repo lang315/camoufox --ref fix/163-162-browser -f build_target=full`.
  Watch it in the background (cold macOS takes about 2 h).
- [ ] **Step 2: Linux guard.** Run the Task 13 guard on this build's Linux
  artifact. Expected: `PASS`. Record the run, build and branch.
- [ ] **Step 3: e2e with B off.** Dispatch
  `e2e.yml -f run_id=<build run>` with the job env
  `CAMOUFOX_NO_GENERIC_PREFS=1`. Add a `generic_prefs` boolean input to
  `e2e.yml` that sets it; it defaults to on. In `on.workflow_dispatch.inputs`:

```yaml
      generic_prefs:
        description: "Set the launchers' #162 generic font prefs (off = measure the browser fix alone)"
        type: boolean
        default: true
```

  On the pytest step's `env:`, add
  `CAMOUFOX_NO_GENERIC_PREFS: ${{ inputs.generic_prefs && '0' || '1' }}`.

  - **Expected `FIXED?` on every host:** every #162 entry (Darwin, Linux,
    Windows), every #163 entry (pkg, pw, go) and the `test_proxy[go-socks5]`
    RAISES entry.
  - **Expected:** `test_context_webrtc_ip_overrides_the_launch_one` is green.
- [ ] **Step 4: e2e with B on.** Dispatch the same `e2e.yml` again with the
  prefs on (the default). Expected: green.
- [ ] **Step 5: Gate and ledger.**
  - The gate (`tests.yml`) is green: build-tester, the patch guards, the
    Playwright suite, and `CAMOU-FL default-unfiltered` at 0 in its logs.
  - Delete the ledger entries that reported `FIXED?`.
  - The PR body lists every run id, resolved to its build and branch, and
    says what the Linux guard cannot see.
- [ ] **Step 6:** Merge.

---

## W4: measure first

### Task 18: The #165 emoji timing probe, with and without the emoji pref

**Files:** Create `e2e/probes/emoji_timing.py`. Modify `goapi/fontenv.go` and
`pythonlib/camoufox/utils.py` only if the decision rule says so.

- [ ] **Step 1: Write the probe**

```python
"""#165 probe: does U+1F603 change face during a context's first seconds?

    python3 e2e/probes/emoji_timing.py --binary BIN --os windows [--emoji-pref] [--mozlog DIR]

Prints one row per fresh context: measureText('😃') at 0, 0.3, 0.8, 1.5 and 3 s.
--emoji-pref sets font.name-list.emoji to the spoofed OS's emoji families.
--mozlog DIR captures MOZ_LOG=timestamp,fontlist:4 for the run.
"""

import argparse
import os
import time

from camoufox.sync_api import Camoufox

EMOJI = {"windows": "Segoe UI Emoji, Twemoji Mozilla", "macos": "Apple Color Emoji", "linux": "Twemoji Mozilla"}
AT = [0, 0.3, 0.8, 1.5, 3]
JS = "(() => { const x = document.createElement('canvas').getContext('2d'); x.font = '16px Arial'; return x.measureText('\\u{1F603}').width; })()"


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--binary", required=True)
    a.add_argument("--os", required=True, choices=EMOJI)
    a.add_argument("--contexts", type=int, default=10)
    a.add_argument("--emoji-pref", action="store_true")
    a.add_argument("--mozlog")
    args = a.parse_args()
    env = dict(os.environ)
    if args.mozlog:
        os.makedirs(args.mozlog, exist_ok=True)
        env.update(MOZ_LOG="timestamp,fontlist:4", MOZ_LOG_FILE=os.path.join(args.mozlog, "moz"))
    prefs = {"font.name-list.emoji": EMOJI[args.os]} if args.emoji_pref else {}
    steady = 0
    with Camoufox(executable_path=args.binary, os=args.os, headless=True, env=env, firefox_user_prefs=prefs) as b:
        for i in range(args.contexts):
            page = b.new_context().new_page()
            page.goto("about:blank")
            t0, row = time.monotonic(), []
            for t in AT:
                time.sleep(max(0, t - (time.monotonic() - t0)))
                row.append(round(page.evaluate(JS), 2))
            steady += len(set(row)) == 1
            print(f"context {i}: {row}", flush=True)
            page.context.close()
    print(f"constant in {steady}/{args.contexts} contexts (emoji pref {'on' if args.emoji_pref else 'off'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Measure.** Run it on macOS (local) and on Linux (buildpc WSL, or
  a dispatched job) against the fork.1 release, `--os windows`. Do four runs:
  pref off and pref on, on each host.
  - Capture `--mozlog` for one pref-off run.
  - Before quoting it, check the log with
    `grep -c "CAMOU-FL default-unfiltered" <log>`.
- [ ] **Step 3: Decide, and post the tables and log excerpt to #165:**
  - **If the pref makes the widths constant in 10/10 on both hosts, and the
    log shows the pref family chosen at t=0:**
    - Add `font.name-list.emoji` to `genericFamilies` and
      `GENERIC_FONT_FAMILIES`, as a fourth element, and emit it once, not per
      lang group.
    - Extend both family tests.
    - Remove the #165 ledger entries after 3 greens.
  - **Otherwise:** append a W5 section to the spec that names the C++ site the
    log points at. Stop for review.

### Task 19: The #171 MOZ_LOG capture mode

**Files:** `e2e/journeys/test_08_lifecycle.py` (`fifty_contexts`), `e2e/drivers/playwright_drivers.py` (a `env` launch parameter), `.github/workflows/e2e.yml` (artifact upload)

- [ ] **Step 1: Driver.** Add `env=None` to `PkgDriver.launch` and `PwDriver.launch`,
  and pass it through as `env=env` in `kw`. It is dropped when `None`, as the
  other keys are. Add `env=None` to `RefDriver.launch` as well, and ignore it.
- [ ] **Step 2: Capture.** In `fifty_contexts`, before `driver.launch()`:

```python
    env = None
    logdir = os.environ.get("E2E_MOZ_LOG")
    if logdir:
        # #171: where does a stalled navigation stop? Per-process logs, timestamped,
        # so the stall's wall-clock time (printed below) finds it in the file.
        os.makedirs(logdir, exist_ok=True)
        env = {**os.environ, "MOZ_LOG": "timestamp,nsHttp:3,nsSocketTransport:3",
               "MOZ_LOG_FILE": os.path.join(logdir, f"{driver.name}-moz")}
    b = driver.launch(env=env) if env else driver.launch()
```

  In the `AssertionError` message, add `at {time.strftime('%H:%M:%S', time.gmtime())} UTC`
  and `log dir {logdir}`. Import `os` at the top.
- [ ] **Step 3: Workflow.** In `.github/workflows/e2e.yml`:
  - Add an input `mozlog` (boolean, default false). When it is true, set
    `E2E_MOZ_LOG=${{ github.workspace }}/.ci-work/mozlog` on the pytest step.
  - Add a step after it:

```yaml
      - if: always() && inputs.mozlog
        uses: actions/upload-artifact@v4
        with:
          name: mozlog-${{ matrix.target }}
          path: .ci-work/mozlog
          retention-days: 7
```

- [ ] **Step 4: Measure.** Run it on W1's build, which has a Linux artifact:
  `gh workflow run e2e.yml ... -f run_id=<W1 build run> -f mozlog=true`, with
  `-k fifty_contexts` passed through the workflow's pytest args if there is an
  input for that. Repeat until 2 stalls are captured.
- [ ] **Step 5: Report.** Download the artifacts and find the stalled
  navigation by its UTC time. Post one of the following to #171, with the log
  lines:
  - no channel was opened;
  - a channel was opened and never connected;
  - it connected and got no response.

  Then append the W5 fix section to the spec. Stop for review.

---

## Self-review

Checked against the spec:
- **W0:** Tasks 0-2 cover all seven procedure steps, plus the explicit
  go-ahead gate and the issue-based evidence.
- **W1:** #163 (Task 14), #162 A with the #131 procedure and lessons 5/7
  (Task 15), #166.3 (Task 16), the Linux RED-first guard (Task 13), and
  evidence with and without B (Task 17).
- **W2:** #166.1-.5 (Tasks 3-5), #162b and B (Task 6), the ledger (Task 7).
- **W3:** #162 B with the hook (Task 8), #163 pythonlib (Task 9), #164a
  (Task 10), #164b (Task 11), the ledger (Task 12).
- **W4:** #165 (Task 18) and #171 (Task 19). W5 is deferred by design.
- **Names used across tasks:**
  - `genericFontPrefs` / `generic_font_prefs` share one table.
  - `CAMOUFOX_NO_GENERIC_PREFS` is read in Tasks 6, 8 and 17.
  - `new_identity_context(**kw)` comes from Task 14; `context_kwargs` from Task 11.
  - `launch_window` is produced in Task 10 and consumed by
    `generate_context_fingerprint`.
- **Changes made against the spec:**
  - W2 Task 6 warns instead of failing when a Linux binary has no bundle
    beside it. The spec did not say which, and failing would break goapi's
    dev-build tests.
  - W3 Task 10 keeps a viewport, equal to the launch inner, when the launch
    has one. That keeps per-context DPR, which Playwright forbids together with
    `no_viewport`. It uses `no_viewport` only when no launch inner is known.
