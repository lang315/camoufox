package fingerprint

import (
	"math/rand/v2"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

func TestGenerateWindowsPreset(t *testing.T) {
	rng := rand.New(rand.NewPCG(1, 2))
	cfg := &config.Config{}
	if err := Generate(cfg, Options{OS: "windows", FirefoxVersion: "134", Rand: rng}); err != nil {
		t.Fatal(err)
	}
	if cfg.NavigatorUserAgent == "" {
		t.Fatal("no user agent")
	}
	if cfg.NavigatorPlatform != "Win32" {
		t.Fatalf("expected Win32 platform, got %q", cfg.NavigatorPlatform)
	}
	if cfg.ScreenWidth == nil || *cfg.ScreenWidth == 0 {
		t.Fatal("no screen width")
	}
	if cfg.CanvasSeed == nil || *cfg.CanvasSeed == 0 {
		t.Fatal("canvas seed unset or zero")
	}
	if len(cfg.Fonts) < 12 {
		t.Fatalf("expected at least 12 fonts (essentials), got %d", len(cfg.Fonts))
	}
	// Marker fonts must always be present.
	for _, m := range windowsMarkerFonts {
		var found bool
		for _, f := range cfg.Fonts {
			if f == m {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("marker font %q missing from windows subset", m)
		}
	}
}

func TestFontSubsetMacOS(t *testing.T) {
	rng := rand.New(rand.NewPCG(42, 0))
	fonts, err := RandomFontSubset("macos", rng)
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range macosMarkerFonts {
		var found bool
		for _, f := range fonts {
			if f == m {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("macos marker %q missing", m)
		}
	}
}

func TestVoiceSubset(t *testing.T) {
	rng := rand.New(rand.NewPCG(7, 0))
	// Linux returns empty.
	v, err := RandomVoiceSubset("linux", rng)
	if err != nil {
		t.Fatal(err)
	}
	if len(v) != 0 {
		t.Fatalf("linux voices should be empty, got %d", len(v))
	}
	// Windows returns everything (no subsetting).
	wv, err := RandomVoiceSubset("windows", rng)
	if err != nil {
		t.Fatal(err)
	}
	if len(wv) == 0 {
		t.Fatal("expected windows voices")
	}
}
