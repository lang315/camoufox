package camoufox_test

import (
	"context"
	"testing"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/config"
)

// The fingerprint is generated before the browser starts, so a launch of a missing
// binary still leaves the drawn identity in the config.
func drawnPlatform(t *testing.T, opts ...camoufox.Option) string {
	t.Helper()
	cfg := &config.Config{}
	opts = append(opts, camoufox.WithConfig(cfg), camoufox.WithExecutablePath("/nonexistent/camoufox"))
	if _, err := camoufox.Launch(context.Background(), opts...); err == nil {
		t.Fatal("launch of a missing binary succeeded")
	}
	return cfg.NavigatorPlatform
}

func TestCamoufoxOSPinsTheIdentity(t *testing.T) {
	t.Setenv("CAMOUFOX_OS", "windows")
	for i := 0; i < 20; i++ {
		if got := drawnPlatform(t); got != "Win32" {
			t.Fatalf("CAMOUFOX_OS=windows drew navigator.platform %q on draw %d", got, i)
		}
	}
	if got := drawnPlatform(t, camoufox.WithOS("macos")); got != "MacIntel" {
		t.Fatalf("WithOS(macos) under CAMOUFOX_OS=windows drew %q; the option must win", got)
	}
}
