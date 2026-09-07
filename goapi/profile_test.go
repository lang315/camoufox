package camoufox_test

import (
	"context"
	"fmt"
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
//
// The probe used to be dom.w3c_touch_events.enabled read back as
// window.TouchEvent. That measures nothing since
// patches/touchscreen-fingerprint-spoofing.patch: TouchEvent::PrefEnabled now
// answers from the CAMOU config whenever navigator.maxTouchPoints is *present*
// (MaskConfig::HasKey is presence-only, additions/camoucfg/MaskConfig.hpp), and
// every one of the 123 fingerprint presets carries that key -- so for a default
// Launch the pref never reaches window.TouchEvent at all. The 22 Windows
// presets that report a digitizer turned the assertion red (smoke runs
// 34127073311 / 34127869783); the other 101 report 0 and would have hidden a
// real leak. Inert in both directions.
//
// dom.webnotifications.enabled replaces it: Notification::PrefEnabled
// (dom/notification/Notification.cpp) returns exactly
// StaticPrefs::dom_webnotifications_enabled(), the pref defaults to true, and
// nothing under patches/, additions/ or settings/ mentions webnotifications, so
// no Camoufox spoof intercepts it. The first launch asserts the pref really
// does gate window.Notification, so the second launch's assertion is a control
// and not a value that would read the same either way.
func TestLaunchUsesAThrowawayProfile(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true),
		camoufox.WithFirefoxUserPref("dom.webnotifications.enabled", false))
	if err != nil {
		t.Fatalf("first launch: %v", err)
	}
	gone, err := notificationIsUndefined(ctx, b)
	if err != nil {
		_ = b.Close()
		t.Fatalf("first launch: %v", err)
	}
	if gone != true {
		_ = b.Close()
		t.Fatalf("dom.webnotifications.enabled=false did not gate window.Notification "+
			"(typeof-undefined = %v): the probe pref is dead, this is not a profile leak", gone)
	}
	if err := b.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	// A second launch that sets no notification pref must not inherit the first's.
	b2, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("second launch: %v", err)
	}
	defer b2.Close()
	got, err := notificationIsUndefined(ctx, b2)
	if err != nil {
		t.Fatalf("second launch: %v", err)
	}
	if got != false {
		t.Errorf("second launch inherited dom.webnotifications.enabled from the first; "+
			"window.Notification should be defined, typeof-undefined = %v", got)
	}
}

// notificationIsUndefined opens a page in a fresh context and reports whether
// window.Notification is absent there, i.e. whether dom.webnotifications.enabled
// is off for that launch.
func notificationIsUndefined(ctx context.Context, b *camoufox.Browser) (any, error) {
	bc, err := b.NewContext(ctx)
	if err != nil {
		return nil, fmt.Errorf("context: %w", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		return nil, fmt.Errorf("page: %w", err)
	}
	v, err := p.Evaluate(ctx, `typeof window.Notification === 'undefined'`)
	if err != nil {
		return nil, fmt.Errorf("evaluate: %w", err)
	}
	return v, nil
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
