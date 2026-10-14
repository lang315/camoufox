package fingerprint

import (
	"math/rand/v2"
	"slices"
	"testing"
)

// Every non-native draw is one machine pythonlib's model can produce (#185):
// one whole OS base, the essential floor, the markers, and otherwise only
// members of addition units.
func TestFontDrawIsOneMachineOfPythonlibsModel(t *testing.T) {
	all, err := loadFonts()
	if err != nil {
		t.Fatal(err)
	}
	for _, osName := range []string{"windows", "macos", "linux"} {
		key := osKey(osName)
		allowed := setOf(essentialFonts[key])
		for _, f := range launcher.MarkerFonts[key] {
			allowed[f] = true
		}
		for _, u := range fontUnits[key] {
			for _, f := range u.Fonts {
				allowed[f] = true
			}
		}
		inFull := setOf(all[key])
		rng := rand.New(rand.NewPCG(11, 12))
		for i := range 300 {
			fonts, err := RandomFontSubset(osName, false, rng)
			if err != nil {
				t.Fatal(err)
			}
			got := setOf(fonts)
			// A base can be a subset of another (Ubuntu 24.04's of 26.04's), so
			// every base present in full counts.
			baseFonts := map[string]bool{}
			for _, b := range fontBases[key] {
				if !slices.ContainsFunc(b.Fonts, func(f string) bool { return !got[f] }) {
					for _, f := range b.Fonts {
						baseFonts[f] = true
					}
				}
			}
			if len(baseFonts) == 0 {
				t.Fatalf("%s draw %d: no OS base is present in full", osName, i)
			}
			for _, f := range essentialFonts[key] {
				if inFull[f] && !got[f] {
					t.Fatalf("%s draw %d: essential %q missing", osName, i, f)
				}
			}
			for _, f := range launcher.MarkerFonts[key] {
				if !got[f] {
					t.Fatalf("%s draw %d: marker %q missing", osName, i, f)
				}
			}
			for _, f := range fonts {
				if !baseFonts[f] && !allowed[f] {
					t.Fatalf("%s draw %d: %q is in no base, unit, marker or essential list", osName, i, f)
				}
			}
			if len(got) != len(fonts) {
				t.Fatalf("%s draw %d: duplicate families", osName, i)
			}
		}
	}
}

// A native identity claims exactly its OS's essential fonts (on a Windows 11
// host, for Windows).
func TestNativeFontDrawIsTheEssentialSet(t *testing.T) {
	saved := hostHasWindows11Fonts
	t.Cleanup(func() { hostHasWindows11Fonts = saved })
	hostHasWindows11Fonts = func() bool { return true }
	for _, osName := range []string{"windows", "macos"} {
		fonts, err := RandomFontSubset(osName, true, rand.New(rand.NewPCG(1, 1)))
		if err != nil {
			t.Fatal(err)
		}
		want, got := setOf(essentialFonts[osKey(osName)]), setOf(fonts)
		if len(got) != len(fonts) || len(got) != len(want) || slices.ContainsFunc(fonts, func(f string) bool { return !want[f] }) {
			t.Fatalf("%s: native draw has %d families, essential-fonts.json %d", osName, len(fonts), len(want))
		}
	}
}

// A Windows 10 host cannot render the Windows 11 families, so a native
// Windows identity there does not claim them.
func TestNativeWindowsDrawOnAWindows10Host(t *testing.T) {
	saved := hostHasWindows11Fonts
	t.Cleanup(func() { hostHasWindows11Fonts = saved })
	hostHasWindows11Fonts = func() bool { return false }
	fonts, err := RandomFontSubset("windows", true, rand.New(rand.NewPCG(1, 1)))
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range launcher.Windows11MarkerFonts {
		if slices.Contains(fonts, f) {
			t.Fatalf("Windows 11 family %q claimed on a Windows 10 host", f)
		}
	}
}
