# goapi Profile Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every `goapi.Launch()` its own throwaway browser profile so prefs and browsing state stop leaking between launches (issue #50).

**Architecture:** `Launch()` currently passes no `-profile`, so Firefox falls back to a persistent default profile keyed per install path. We create a temp directory per launch, pass `-profile <dir>`, and remove it in `Close()`. An opt-in `WithUserDataDir()` covers callers who genuinely want persistence — explicit rather than accidental.

**Tech Stack:** Go 1.23, `os.MkdirTemp`, `exec.CommandContext`. No new dependencies.

## Global Constraints

- Go module lives in `goapi/`; run all commands from that directory.
- `go vet ./...` and `go build ./...` must stay clean.
- Browser-dependent tests must `t.Skip` when `CAMOUFOX_BIN` is unset — this is the existing convention in every `*_test.go` in `goapi/`, and CI (`goapi.yml`) runs without a binary.
- `goapi/pkg/config/config.go` is NOT gofmt-clean at HEAD. Do not run `gofmt -w` on it; it would produce a 40-line whitespace diff in unrelated blocks.
- Never delete a directory path the caller supplied. Only remove directories this code created.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `goapi/options.go` | Launch options + `launchConfig` fields | Add `userDataDir` field and `WithUserDataDir` option |
| `goapi/launch.go` | Builds the CLI, owns `Browser` lifecycle | Create temp profile, pass `-profile`, record it on `Browser`, remove it in `Close()` |
| `goapi/profile_test.go` | New — unit + integration coverage for isolation | Create |

---

### Task 1: Temp profile per launch, removed on Close

**Files:**
- Modify: `goapi/options.go:15-37` (add field), and the option list below it
- Modify: `goapi/launch.go:120` (args), `goapi/launch.go:24-40` (Browser struct), `goapi/launch.go:406-425` (Close)
- Test: `goapi/profile_test.go` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WithUserDataDir(dir string) Option`; `Browser.profileDir string` (unexported, set only when goapi created the directory); `Browser.ownsProfileDir bool`.

- [ ] **Step 1: Write the failing test**

Create `goapi/profile_test.go`:

```go
package camoufox_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

// #50: two independent Launch() calls must not share browser state. The
// regression was that no -profile was passed, so Firefox used a persistent
// default profile keyed per install path and every WithFirefoxUserPref
// written by one launch was inherited by the next.
func TestLaunchUsesAThrowawayProfile(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true),
		camoufox.WithFirefoxUserPref("dom.w3c_touch_events.enabled", 1))
	if err != nil {
		t.Fatalf("first launch: %v", err)
	}
	if err := b.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	// A second launch that sets no touch pref must not inherit the first's.
	b2, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("second launch: %v", err)
	}
	defer b2.Close()
	bc, err := b2.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	got, err := p.Evaluate(ctx, `typeof window.TouchEvent === 'undefined'`)
	if err != nil {
		t.Fatalf("evaluate: %v", err)
	}
	if got != true {
		t.Errorf("second launch inherited dom.w3c_touch_events.enabled from the first; "+
			"window.TouchEvent should be undefined, got %v", got)
	}
}

// The profile directory goapi creates must not survive Close().
func TestCloseRemovesTheProfileDirectory(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	before, err := filepath.Glob(filepath.Join(os.TempDir(), "camoufox-profile-*"))
	if err != nil {
		t.Fatal(err)
	}
	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	if err := b.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}
	after, err := filepath.Glob(filepath.Join(os.TempDir(), "camoufox-profile-*"))
	if err != nil {
		t.Fatal(err)
	}
	if len(after) > len(before) {
		t.Errorf("Close() leaked a profile dir: %d before, %d after", len(before), len(after))
	}
}

// A caller-supplied dir is used as-is and must NOT be deleted -- it is the
// caller's data, and deleting it would be destructive.
func TestWithUserDataDirIsPreserved(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	dir := t.TempDir()
	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true),
		camoufox.WithUserDataDir(dir))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	if err := b.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}
	if _, err := os.Stat(dir); err != nil {
		t.Errorf("caller-supplied user data dir was removed: %v", err)
	}
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd goapi && go test -run 'TestLaunchUsesAThrowawayProfile|TestCloseRemovesTheProfileDirectory|TestWithUserDataDirIsPreserved' .`

Expected: compile error — `undefined: camoufox.WithUserDataDir`. That is the correct first failure; the option does not exist yet.

- [ ] **Step 3: Add the option**

In `goapi/options.go`, add to the `launchConfig` struct (after the `virtualDisplay string` field at line 22):

```go
	userDataDir     string
```

Then add the option next to the other `With*` functions:

```go
// WithUserDataDir runs the browser against a caller-owned profile directory
// instead of a throwaway one. State (cookies, localStorage, prefs) then
// persists across launches, and goapi never deletes the directory.
//
// Without this, each Launch gets a fresh temp profile that Close removes.
// That default exists because a shared profile links sessions that callers
// expect to be independent -- see issue #50.
func WithUserDataDir(dir string) Option {
	return func(c *launchConfig) { c.userDataDir = dir }
}
```

- [ ] **Step 4: Create the profile and pass it to Firefox**

In `goapi/launch.go`, replace the args construction at line 120:

```go
	args := []string{"--juggler-pipe", "--no-remote"}
	if lc.headless {
		args = append(args, "--headless")
	}
```

with:

```go
	// Without an explicit -profile, Firefox falls back to a persistent default
	// profile keyed per install path, so prefs and browsing state leak between
	// launches that callers expect to be independent (#50).
	profileDir := lc.userDataDir
	ownsProfileDir := false
	if profileDir == "" {
		profileDir, err = os.MkdirTemp("", "camoufox-profile-")
		if err != nil {
			return nil, fmt.Errorf("camoufox: create profile dir: %w", err)
		}
		ownsProfileDir = true
	}

	args := []string{"--juggler-pipe", "--no-remote", "-profile", profileDir}
	if lc.headless {
		args = append(args, "--headless")
	}
```

- [ ] **Step 5: Record it on the Browser and clean up on Close**

In `goapi/launch.go`, add to the `Browser` struct (after the `debug bool` field):

```go
	// profileDir is removed by Close only when ownsProfileDir is true --
	// a caller-supplied WithUserDataDir is their data, never ours to delete.
	profileDir     string
	ownsProfileDir bool
```

Set both fields wherever the `Browser` value is constructed in `Launch`, alongside `debug: lc.debug`:

```go
		profileDir:     profileDir,
		ownsProfileDir: ownsProfileDir,
```

Then in `Close()` (line 406), add cleanup as the last step before `return nil`:

```go
	if b.ownsProfileDir && b.profileDir != "" {
		_ = os.RemoveAll(b.profileDir)
	}
	return nil
```

Note: the cleanup runs after the process wait block that already exists, so the browser has exited and released its profile lock before the directory is removed.

- [ ] **Step 6: Handle the early-failure path**

Still in `Launch`, every `return nil, err` between the `os.MkdirTemp` call and the successful construction of the `Browser` now leaks the directory. Immediately after the `MkdirTemp` block, add:

```go
	launched := false
	defer func() {
		if ownsProfileDir && !launched {
			_ = os.RemoveAll(profileDir)
		}
	}()
```

and set `launched = true` on the line immediately before `Launch` returns the `Browser` successfully.

- [ ] **Step 7: Verify imports**

`goapi/launch.go` already imports `os` and `fmt` (used elsewhere in the file). Confirm with:

Run: `cd goapi && go build ./...`
Expected: no output, exit 0.

- [ ] **Step 8: Run the unit suite**

Run: `cd goapi && go vet ./... && go test ./...`
Expected: all packages `ok`. The three new tests SKIP without `CAMOUFOX_BIN`.

- [ ] **Step 9: Run the new tests against a real binary**

Run: `cd goapi && CAMOUFOX_BIN=/path/to/camoufox go test -run 'TestLaunchUsesAThrowawayProfile|TestCloseRemovesTheProfileDirectory|TestWithUserDataDirIsPreserved' -v .`
Expected: all three PASS.

- [ ] **Step 10: Confirm the original symptom is gone**

`TestRuntimeSpoofs/touch_trio` was permanently red on any machine where a touch test had run, because the leaked pref made `window.TouchEvent` defined. With isolation it must pass repeatedly:

Run: `cd goapi && for i in 1 2 3; do CAMOUFOX_BIN=/path/to/camoufox go test -run 'TestRuntimeSpoofs/touch_trio' -count=1 .; done`
Expected: `ok` three times.

- [ ] **Step 11: Commit**

```bash
git add goapi/options.go goapi/launch.go goapi/profile_test.go
git commit -m "fix(goapi): give each Launch its own throwaway profile (#50)"
```

---

## Notes for the implementer

Existing poisoned profiles on a dev machine are NOT cleaned up by this change. On macOS they live in `~/Library/Application Support/camoufox/Profiles/`. Removing them is the user's call — do not delete them as part of this task.

A `HOME` override does not redirect the profile location on macOS: Firefox resolves the app-support directory through Cocoa using the real `getpwuid` home. If you need a clean profile for manual comparison, copy the `.app` to a new path — Firefox keys its default profile per install path (`[Install<hash>]` in `profiles.ini`).
