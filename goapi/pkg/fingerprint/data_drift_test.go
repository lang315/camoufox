package fingerprint

import (
	"bytes"
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

// The font-draw tables and launcher constants are pythonlib's own files; a
// drifted copy draws a machine pythonlib would not (#185).
func TestEmbeddedLauncherDataMatchesPythonlib(t *testing.T) {
	for name, got := range map[string][]byte{
		"font-bases.json":         rawFontBases,
		"font-groups.json":        rawFontGroups,
		"essential-fonts.json":    rawEssentialFonts,
		"launcher-constants.json": rawLauncherConstants,
		"voice-manifests.json":    rawVoiceManifests,
		"voice-uris.json":         rawVoiceURIs,
	} {
		src := filepath.Join("..", "..", "..", "python", "src", "camoufox", name)
		want, err := os.ReadFile(src)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, want) {
			t.Errorf("data/%s differs from %s; refresh it: cp %s goapi/pkg/fingerprint/data/%s", name, src, src, name)
		}
	}
}
