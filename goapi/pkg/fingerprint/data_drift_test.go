package fingerprint

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// fonts.json is the pool the font draw samples from. pythonlib holds the one
// regenerated copy (scripts/gen-fonts-json.py); the embedded one must be
// byte-identical, or this launcher draws names the bundle does not ship.
func TestEmbeddedFontsMatchPythonlib(t *testing.T) {
	src := filepath.Join("..", "..", "..", "pythonlib", "camoufox", "fonts.json")
	want, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(rawFonts, want) {
		t.Fatalf("data/fonts.json differs from pythonlib/camoufox/fonts.json; refresh it: cp %s goapi/pkg/fingerprint/data/fonts.json", src)
	}
}
