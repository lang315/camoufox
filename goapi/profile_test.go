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
