package fingerprint

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// fonts.json is the pool the font draw samples from. pythonlib holds the one
// regenerated copy (browser/scripts/gen-fonts-json.py); the embedded one must be
// byte-identical, or this launcher draws names the bundle does not ship.
func TestEmbeddedFontsMatchPythonlib(t *testing.T) {
	src := filepath.Join("..", "..", "..", "python", "src", "camoufox", "fonts.json")
	want, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(rawFonts, want) {
		t.Fatalf("data/fonts.json differs from python/src/camoufox/fonts.json; refresh it: cp %s goapi/pkg/fingerprint/data/fonts.json", src)
	}
}

// fingerprint-presets.json is the preset pool; pythonlib holds the one copy
// python/scripts/clean_presets.py maintains. goapi kept ten presets that script
// had removed (#185), so it could draw an identity pythonlib refuses.
func TestEmbeddedPresetsMatchPythonlib(t *testing.T) {
	src := filepath.Join("..", "..", "..", "python", "src", "camoufox", "fingerprint-presets.json")
	want, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(rawPresets, want) {
		t.Fatalf("data/fingerprint-presets.json differs from %s; refresh it: cp %s goapi/pkg/fingerprint/data/fingerprint-presets.json", src, src)
	}
}

// The baseline taskbar heights and touch points are pythonlib's
// launcher-constants.json values; a drifted copy claims an avail screen the
// browser does not report.
func TestBaselineConstantsMatchPythonlib(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "python", "src", "camoufox", "launcher-constants.json"))
	if err != nil {
		t.Fatal(err)
	}
	var c struct {
		Taskbar map[string]uint32 `json:"baselineTaskbarHeight"`
		Touch   uint32            `json:"baselineMultiTouchPoints"`
	}
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	for key, osName := range map[string]string{"win": "windows", "mac": "macos", "lin": "linux"} {
		if got, ok := baselineTaskbarHeight[osName]; !ok || got != c.Taskbar[key] {
			t.Errorf("baselineTaskbarHeight[%q] = %d, launcher-constants.json says %d", osName, got, c.Taskbar[key])
		}
	}
	if baselineMultiTouchPoints != c.Touch {
		t.Errorf("baselineMultiTouchPoints = %d, launcher-constants.json says %d", baselineMultiTouchPoints, c.Touch)
	}
}
