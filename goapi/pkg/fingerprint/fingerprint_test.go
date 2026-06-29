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

// TestMediaCodecProfile guards #6: HEVC must be supported+coherent on
// Windows/macOS and unsupported on Linux across canPlayType + decodingInfo.
func TestMediaCodecProfile(t *testing.T) {
	cases := map[string]bool{"windows": true, "macos": true, "linux": false}
	for os, wantHEVC := range cases {
		cfg := &config.Config{}
		if err := Generate(cfg, Options{OS: os, Rand: rand.New(rand.NewPCG(5, 6))}); err != nil {
			t.Fatal(err)
		}
		cp := cfg.MediaCanPlayType["hvc1"]
		dec := cfg.MediaDecodingInfo["hvc1"]
		if wantHEVC {
			if cp != "probably" || !dec.Supported || !dec.PowerEfficient {
				t.Errorf("%s: HEVC should be supported, got canPlay=%q dec=%+v", os, cp, dec)
			}
		} else {
			if cp != "" || dec.Supported {
				t.Errorf("%s: HEVC should be unsupported, got canPlay=%q dec=%+v", os, cp, dec)
			}
		}
	}
}

// TestVoiceLangCoherence guards #13: each generated voice must carry its real
// lang/localService, not a hardcoded en-US. Daniel (en-GB) and Karen (en-AU)
// are essential macOS voices, so they are always present.
func TestVoiceLangCoherence(t *testing.T) {
	cfg := &config.Config{}
	if err := Generate(cfg, Options{OS: "macos", Rand: rand.New(rand.NewPCG(3, 4))}); err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"Daniel": "en-GB", "Karen": "en-AU", "Samantha": "en-US"}
	seen := map[string]string{}
	for _, v := range cfg.Voices {
		if exp, ok := want[v.Name]; ok {
			seen[v.Name] = v.Lang
			if v.Lang != exp {
				t.Errorf("voice %q lang = %q, want %q", v.Name, v.Lang, exp)
			}
		}
		if !v.IsLocalService {
			t.Errorf("voice %q should be local", v.Name)
		}
	}
	for n := range want {
		if _, ok := seen[n]; !ok {
			t.Errorf("essential macOS voice %q not generated", n)
		}
	}
}
