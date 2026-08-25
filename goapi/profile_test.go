package camoufox_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
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

// A caller-supplied dir is actually used as the Firefox profile, and is used
// as-is -- it must NOT be deleted, since it is the caller's data and
// deleting it would be destructive.
func TestWithUserDataDirIsUsedAndPreserved(t *testing.T) {
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

	// If WithUserDataDir were dropped and a temp profile used instead, dir
	// (a t.TempDir()) would still exist and the check above would still
	// pass. Assert Firefox actually wrote its profile into the caller's
	// dir, e.g. prefs.js / times.json / compatibility.ini.
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read user data dir: %v", err)
	}
	if len(entries) == 0 {
		t.Error("WithUserDataDir was ignored: Firefox wrote nothing into the caller's dir")
	}
}

// The guard runs before the executable is touched, so unlike the rest of this
// file it needs no CAMOUFOX_BIN and actually executes in CI.
//
// Passing -profile via WithArgs used to work (it was the only such flag). Now
// Launch prepends its own and Firefox honors the first, so the caller's would
// be dropped silently AND the profile actually used would be a temp dir that
// Close deletes -- no persistence at all, no error. Reject it instead.
func TestLaunchRejectsProfileViaWithArgs(t *testing.T) {
	for _, flag := range []string{"-profile", "--profile"} {
		_, err := camoufox.Launch(context.Background(),
			camoufox.WithExecutablePath("/nonexistent/camoufox-does-not-exist"),
			camoufox.WithArgs(flag, "/tmp/some-profile-dir"))
		if err == nil {
			t.Fatalf("%s via WithArgs: expected an error, got nil", flag)
		}
		if !strings.Contains(err.Error(), "WithUserDataDir") {
			t.Errorf("%s via WithArgs: error should name WithUserDataDir as the replacement, got: %v", flag, err)
		}
	}
}
