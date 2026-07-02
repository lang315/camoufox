package fingerprint

import (
	"strings"
	"testing"
)

// TestPresetCoherence enforces cross-signal coherence on every bundled preset:
// WebGL identity, speech voices, and platform must all agree with one base OS.
// A Windows UA with an Apple GPU, or a macOS UA with a Direct3D/ANGLE renderer,
// is a physically impossible device and an instant anti-bot flag. This guards
// the fingerprint dataset against edits that trade one leak for a contradiction.
// See plan/anti-detect-review-and-optimize.md (T7).
func TestPresetCoherence(t *testing.T) {
	pf, err := loadPresets()
	if err != nil {
		t.Fatal(err)
	}
	wantPlatform := map[string]string{
		"windows": "Win32",
		"macos":   "MacIntel",
		"linux":   "Linux x86_64",
	}
	for osKey, presets := range pf.Presets {
		if _, ok := wantPlatform[osKey]; !ok {
			t.Errorf("unknown OS group %q in presets", osKey)
		}
		for i, p := range presets {
			plat := p.Navigator.Platform
			if wp := wantPlatform[osKey]; wp != "" && plat != wp {
				t.Errorf("%s[%d]: platform %q, want %q for OS group", osKey, i, plat, wp)
			}

			v, r := p.WebGL.UnmaskedVendor, p.WebGL.UnmaskedRenderer
			// ANGLE / Direct3D is a Windows-only WebGL backend in Firefox.
			if (strings.Contains(r, "ANGLE") || strings.Contains(r, "Direct3D")) && plat != "Win32" {
				t.Errorf("%s[%d]: ANGLE/Direct3D renderer %q on non-Windows platform %q", osKey, i, r, plat)
			}
			switch plat {
			case "MacIntel":
				if strings.Contains(v, "Google Inc.") || strings.Contains(r, "ANGLE") || strings.Contains(r, "Direct3D") {
					t.Errorf("%s[%d]: macOS preset has Windows-style WebGL vendor=%q renderer=%q", osKey, i, v, r)
				}
			case "Win32":
				if strings.Contains(v, "Apple") || strings.Contains(r, "Apple") {
					t.Errorf("%s[%d]: Windows preset has Apple WebGL vendor=%q renderer=%q", osKey, i, v, r)
				}
			}

			// Speech voices must belong to the OS voice family.
			if len(p.SpeechVoices) > 0 {
				first := p.SpeechVoices[0]
				if plat == "Win32" && !strings.HasPrefix(first, "Microsoft") {
					t.Errorf("%s[%d]: Windows preset first voice %q is not a Microsoft voice", osKey, i, first)
				}
				if plat == "MacIntel" && strings.HasPrefix(first, "Microsoft") {
					t.Errorf("%s[%d]: macOS preset has a Microsoft voice %q", osKey, i, first)
				}
			}
		}
	}
}
