package fingerprint

import (
	"math/rand/v2"
	"sort"
)

// Marker fonts CreepJS uses to detect OS (must always be present).
var (
	macosMarkerFonts   = []string{"Helvetica Neue", "PingFang HK", "PingFang SC", "PingFang TC"}
	linuxMarkerFonts   = []string{"Arimo", "Cousine", "Tinos", "Twemoji Mozilla"}
	windowsMarkerFonts = []string{"Segoe UI", "Tahoma", "Cambria Math", "Nirmala UI"}
)

// Essential fonts per OS that must always be included.
var (
	essentialMacOS = []string{
		"Arial", "Helvetica", "Times New Roman", "Courier New", "Verdana",
		"Georgia", "Trebuchet MS", "Tahoma", "Helvetica Neue", "Lucida Grande",
		"Menlo", "Monaco", "Geneva", "PingFang HK", "PingFang SC", "PingFang TC",
	}
	essentialWindows = []string{
		"Arial", "Times New Roman", "Courier New", "Verdana", "Georgia",
		"Trebuchet MS", "Tahoma", "Segoe UI", "Calibri", "Cambria Math",
		"Nirmala UI", "Consolas",
	}
	essentialLinux = []string{
		"Arimo", "Cousine", "Tinos", "Twemoji Mozilla",
		"Noto Sans Devanagari", "Noto Sans JP", "Noto Sans KR",
		"Noto Sans SC", "Noto Sans TC",
	}
)

// RandomFontSubset mirrors pythonlib/camoufox/fingerprints.py:_generate_random_font_subset.
// Picks 30-78% of non-essential fonts at random, always preserves
// essential + marker fonts.
func RandomFontSubset(targetOS string, rng *rand.Rand) ([]string, error) {
	fonts, err := loadFonts()
	if err != nil {
		return nil, err
	}
	full := fonts[osKey(targetOS)]
	if len(full) == 0 {
		full = fonts["mac"]
	}

	var essential []string
	var markers []string
	switch presetKey(targetOS) {
	case "windows":
		essential = essentialWindows
		markers = windowsMarkerFonts
	case "linux":
		essential = essentialLinux
		markers = linuxMarkerFonts
	default:
		essential = essentialMacOS
		markers = macosMarkerFonts
	}

	essentialSet := setOf(essential)

	result := make([]string, 0, len(full)/2+len(essential)+len(markers))
	nonEssential := make([]string, 0, len(full))
	for _, f := range full {
		if essentialSet[f] {
			result = append(result, f)
		} else {
			nonEssential = append(nonEssential, f)
		}
	}

	pct := 30 + rngInt(rng, 49) // [30, 78]
	count := min(int(float64(pct)/100.0*float64(len(nonEssential))+0.5), len(nonEssential))
	result = append(result, sampleN(nonEssential, count, rng)...)
	return appendMissing(result, markers), nil
}

// LaunchFontWhitelist mirrors pythonlib/camoufox/utils.py:_launch_font_whitelist.
// It returns every bundled family across all OSes -- the value of
// `fonts:whitelist` -- and is NOT the value of Fonts, which stays this
// profile's random per-OS subset (see RandomFontSubset).
//
// font-hijacker.patch writes fonts:whitelist into font.system.whitelist, and
// upstream ApplyWhitelist() then deletes every family outside it from
// mFontFamilies. Narrowing that to one OS is what made a per-context
// setFontList() unable to widen back (#44): the families were already gone.
// The union keeps all bundled families alive at startup so the per-context
// filter can still narrow each context to its own OS.
func LaunchFontWhitelist() ([]string, error) {
	fonts, err := loadFonts()
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	for _, list := range fonts {
		for _, f := range list {
			seen[f] = true
		}
	}
	union := make([]string, 0, len(seen))
	for f := range seen {
		union = append(union, f)
	}
	sort.Strings(union)
	return union, nil
}

// RandomVoiceSubset mirrors _generate_random_voice_subset.
// macOS: 40-80% random subset, essentials always present.
// Windows: every voice.
// Linux: empty.
func RandomVoiceSubset(targetOS string, rng *rand.Rand) ([]string, error) {
	voices, err := loadVoices()
	if err != nil {
		return nil, err
	}
	full := voices[osKey(targetOS)]
	if len(full) == 0 {
		return []string{}, nil
	}
	switch presetKey(targetOS) {
	case "windows":
		out := make([]string, len(full))
		copy(out, full)
		return out, nil
	case "linux":
		return []string{}, nil
	}
	essential := setOf([]string{"Samantha", "Alex", "Fred", "Victoria", "Karen", "Daniel"})
	result := make([]string, 0, len(full))
	nonEssential := make([]string, 0, len(full))
	for _, v := range full {
		if essential[v] {
			result = append(result, v)
		} else {
			nonEssential = append(nonEssential, v)
		}
	}
	pct := 40 + rngInt(rng, 41) // [40, 80]
	count := min(int(float64(pct)/100.0*float64(len(nonEssential))+0.5), len(nonEssential))
	result = append(result, sampleN(nonEssential, count, rng)...)
	return result, nil
}

// setOf returns a string→true map for membership tests.
func setOf(xs []string) map[string]bool {
	m := make(map[string]bool, len(xs))
	for _, x := range xs {
		m[x] = true
	}
	return m
}

// appendMissing returns xs with any element of extras that is not
// already present appended at the end.
func appendMissing(xs []string, extras []string) []string {
	have := setOf(xs)
	for _, e := range extras {
		if !have[e] {
			xs = append(xs, e)
			have[e] = true
		}
	}
	return xs
}

// sampleN returns n random elements of xs without replacement.
func sampleN(xs []string, n int, rng *rand.Rand) []string {
	if n >= len(xs) {
		out := make([]string, len(xs))
		copy(out, xs)
		return out
	}
	if n <= 0 {
		return nil
	}
	idx := rng.Perm(len(xs))[:n]
	out := make([]string, n)
	for i, j := range idx {
		out[i] = xs[j]
	}
	return out
}

// rngInt returns a uniform int in [0, n).
func rngInt(rng *rand.Rand, n int) int {
	if rng == nil {
		return rand.IntN(n)
	}
	return rng.IntN(n)
}
