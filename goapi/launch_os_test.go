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

func TestDefaultOSPinsTheIdentity(t *testing.T) {
	t.Cleanup(camoufox.SetDefaultOS("windows"))
	for i := 0; i < 20; i++ {
		if got := drawnPlatform(t); got != "Win32" {
			t.Fatalf("default OS windows drew navigator.platform %q on draw %d", got, i)
		}
	}
	if got := drawnPlatform(t, camoufox.WithOS("macos")); got != "MacIntel" {
		t.Fatalf("WithOS(macos) under default OS windows drew %q; the option must win", got)
	}
}
