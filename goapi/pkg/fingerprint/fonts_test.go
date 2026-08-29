package fingerprint

import (
	"math/rand/v2"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// TestLaunchFontWhitelistIsTheUnion mirrors
// pythonlib/tests/test_font_union_whitelist.py: the launch-time whitelist
// must be every bundled family across all OSes, not one OS's subset, so a
// per-context setFontList() can widen back to any OS the launch config
// didn't ask for (#44).
func TestLaunchFontWhitelistIsTheUnion(t *testing.T) {
	fonts, err := loadFonts()
	if err != nil {
		t.Fatal(err)
	}
	got, err := LaunchFontWhitelist()
	if err != nil {
		t.Fatal(err)
	}
	gotSet := setOf(got)
	if len(got) != 732 {
		t.Fatalf("expected the 732-family union, got %d", len(got))
	}
	for _, osKey := range []string{"win", "mac", "lin"} {
		for _, f := range fonts[osKey] {
			if !gotSet[f] {
				t.Errorf("%s family %q absent from the launch whitelist", osKey, f)
			}
		}
	}
}

// TestLaunchFontWhitelistDoesNotWidenFonts guards the split this key exists
// for: Fonts (the per-profile subset RandomFontSubset produces) must stay a
// subset, never widened to the whitelist's union. Widening it would make
// every launch-level fallback report all 732 bundled families -- a list no
// real machine has, and a worse tell than the bug being fixed.
func TestLaunchFontWhitelistDoesNotWidenFonts(t *testing.T) {
	rng := rand.New(rand.NewPCG(1, 2))
	subset, err := RandomFontSubset("windows", rng)
	if err != nil {
		t.Fatal(err)
	}
	if len(subset) >= 732 {
		t.Fatalf("the per-profile Fonts subset must stay a subset, got %d families", len(subset))
	}
}

// TestGenerateSetsFontsWhitelist checks the Generate() chokepoint: it must
// populate cfg.FontsWhitelist with the union alongside cfg.Fonts, without
// the two ever being conflated.
func TestGenerateSetsFontsWhitelist(t *testing.T) {
	cfg := &config.Config{}
	if err := Generate(cfg, Options{OS: "windows", Rand: rand.New(rand.NewPCG(9, 9))}); err != nil {
		t.Fatal(err)
	}
	if len(cfg.FontsWhitelist) != 732 {
		t.Fatalf("expected cfg.FontsWhitelist to be the 732-family union, got %d", len(cfg.FontsWhitelist))
	}
	if len(cfg.Fonts) >= 732 {
		t.Fatalf("cfg.Fonts must stay the per-OS subset, got %d families", len(cfg.Fonts))
	}
}

// A caller may pre-set cfg.Fonts to families installed on the host. Those are
// not in the bundled union, and font-hijacker.patch feeds fonts:whitelist to
// font.system.whitelist, where upstream ApplyWhitelist() deletes every family
// outside it -- so a bundled-only whitelist would delete exactly what the
// caller asked for.
func TestCallerFontsSurviveTheWhitelist(t *testing.T) {
	cfg := &config.Config{Fonts: []string{"My Private Font", "Wingdings 3"}}
	if err := Generate(cfg, Options{OS: "windows", Rand: rand.New(rand.NewPCG(1, 2))}); err != nil {
		t.Fatal(err)
	}
	got := setOf(cfg.FontsWhitelist)
	for _, f := range []string{"My Private Font", "Wingdings 3"} {
		if !got[f] {
			t.Errorf("caller font %q missing from fonts:whitelist; it would be deleted at startup", f)
		}
	}
	if len(cfg.FontsWhitelist) <= 732 {
		t.Errorf("whitelist = %d entries, want the 732-family union plus the caller's",
			len(cfg.FontsWhitelist))
	}
}
