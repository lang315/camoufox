package fingerprint

import (
	_ "embed"
	"encoding/json"
)

// Copies of pythonlib's data files, kept byte-identical by data_drift_test.go,
// so the two launchers draw from one source (#185).
var (
	//go:embed data/font-bases.json
	rawFontBases []byte
	//go:embed data/font-groups.json
	rawFontGroups []byte
	//go:embed data/essential-fonts.json
	rawEssentialFonts []byte
	//go:embed data/launcher-constants.json
	rawLauncherConstants []byte
)

// fontBase is one OS version's whole default font set, drawn by weight.
type fontBase struct {
	Weight float64  `json:"weight"`
	Fonts  []string `json:"fonts"`
}

// fontUnit is one addition (an Office install, a language pack), drawn at its
// own measured probability. An "alacarte" unit contributes Sizes of its members.
type fontUnit struct {
	Kind           string   `json:"kind"`
	Prob           float64  `json:"prob"`
	Fonts          []string `json:"fonts"`
	RequiresLocale string   `json:"requiresLocale"`
	Sizes          []struct {
		N int     `json:"n"`
		W float64 `json:"w"`
	} `json:"sizes"`
}

// The embedded files are part of the build; one that does not parse is a
// defect the drift tests catch, not a runtime condition.
var (
	fontBases      = mustParse[map[string][]fontBase](rawFontBases)
	fontUnits      = mustParse[map[string][]fontUnit](rawFontGroups)
	essentialFonts = mustParse[map[string][]string](rawEssentialFonts)
	launcher       = mustParse[struct {
		MarkerFonts              map[string][]string `json:"markerFonts"`
		Windows11MarkerFonts     []string            `json:"windows11MarkerFonts"`
		BaselineTaskbarHeight    map[string]uint32   `json:"baselineTaskbarHeight"`
		BaselineMultiTouchPoints uint32              `json:"baselineMultiTouchPoints"`
		MacNoveltyVoices         []string            `json:"macNoveltyVoices"`
		MacEloquenceVoices       []string            `json:"macEloquenceVoices"`
	}](rawLauncherConstants)
)

func mustParse[T any](raw []byte) T {
	var v T
	if err := json.Unmarshal(raw, &v); err != nil {
		panic("fingerprint: embedded data: " + err.Error())
	}
	return v
}
