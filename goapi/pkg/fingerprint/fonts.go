package fingerprint

import (
	"math/rand/v2"
	"os"
	"path/filepath"
	"slices"
)

// RandomFontSubset mirrors _generate_random_font_subset
// (python/src/camoufox/fingerprints.py): the font list of one plausible machine.
// A machine runs one OS version, so one base (font-bases.json) is drawn by
// weight and kept whole; the essential floor is added, then each addition unit
// (font-groups.json) at its own measured probability, then the marker fonts.
//
// native: the identity is the host's own macOS or Windows, where the browser
// renders the real system fonts, so only the OS's essential fonts are claimed:
// an addition the host does not have would render as a fallback a page can see.
func RandomFontSubset(targetOS string, native bool, rng *rand.Rand) ([]string, error) {
	fonts, err := loadFonts()
	if err != nil {
		return nil, err
	}
	key := osKey(targetOS)
	full := fonts[key]
	essential := setOf(essentialFonts[key])

	if native {
		result := make([]string, 0, len(essential))
		inFull := setOf(full)
		for _, f := range full {
			if essential[f] {
				result = append(result, f)
			}
		}
		var extra []string
		for f := range essential {
			if !inFull[f] {
				extra = append(extra, f)
			}
		}
		slices.Sort(extra)
		result = append(result, extra...)
		// A Windows 10 host cannot render the Windows 11 families.
		if key == "win" && !hostHasWindows11Fonts() {
			result = slices.DeleteFunc(result, func(f string) bool {
				return slices.Contains(launcher.Windows11MarkerFonts, f)
			})
		}
		return result, nil
	}

	result := pickBase(key, rng)
	if len(result) == 0 {
		for _, f := range full {
			if essential[f] {
				result = append(result, f)
			}
		}
	}
	chosen := setOf(result)
	for _, f := range full {
		if essential[f] && !chosen[f] {
			result = append(result, f)
			chosen[f] = true
		}
	}
	for _, f := range drawUnits(key, rng, chosen) {
		if !chosen[f] {
			result = append(result, f)
			chosen[f] = true
		}
	}
	return appendMissing(result, launcher.MarkerFonts[key]), nil
}

// pickBase draws one OS-version base by its weight (_pick_base).
func pickBase(key string, rng *rand.Rand) []string {
	bases := fontBases[key]
	if len(bases) == 0 {
		return nil
	}
	roll, cumulative := rngFloat(rng), 0.0
	for _, b := range bases {
		cumulative += b.Weight
		if roll < cumulative {
			return slices.Clone(b.Fonts)
		}
	}
	return slices.Clone(bases[len(bases)-1].Fonts)
}

// drawUnits returns the additions one machine has (_draw_units): a "bundle"
// unit is all or nothing; an "alacarte" unit, once present, contributes a
// count of its members drawn from its measured sizes. A unit that requires a
// locale is skipped, as pythonlib's launcher draws with none.
func drawUnits(key string, rng *rand.Rand, exclude map[string]bool) []string {
	var out []string
	for _, u := range fontUnits[key] {
		if u.RequiresLocale != "" || rngFloat(rng) >= u.Prob {
			continue
		}
		members := slices.DeleteFunc(slices.Clone(u.Fonts), func(f string) bool { return exclude[f] })
		if len(members) == 0 {
			continue
		}
		if u.Kind == "alacarte" {
			count := len(members)
			if len(u.Sizes) > 0 {
				total := 0.0
				for _, sz := range u.Sizes {
					total += sz.W
				}
				roll, cumulative := rngFloat(rng)*total, 0.0
				count = u.Sizes[len(u.Sizes)-1].N
				for _, sz := range u.Sizes {
					cumulative += sz.W
					if roll < cumulative {
						count = sz.N
						break
					}
				}
			}
			members = sampleN(members, max(1, min(count, len(members))), rng)
		}
		out = append(out, members...)
	}
	return out
}

// hostHasWindows11Fonts reports whether this Windows host ships Segoe UI
// Variable, present on every Windows 11 install and on no Windows 10
// (_host_has_variant_fonts). A variable so tests can stand in for a host.
var hostHasWindows11Fonts = func() bool {
	windir := os.Getenv("WINDIR")
	if windir == "" {
		windir = `C:\Windows`
	}
	_, err := os.Stat(filepath.Join(windir, "Fonts", "SegUIVar.ttf"))
	return err == nil
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

// rngFloat returns a uniform float64 in [0, 1).
func rngFloat(rng *rand.Rand) float64 {
	if rng == nil {
		return rand.Float64()
	}
	return rng.Float64()
}

// rngInt returns a uniform int in [0, n).
func rngInt(rng *rand.Rand, n int) int {
	if rng == nil {
		return rand.IntN(n)
	}
	return rng.IntN(n)
}
