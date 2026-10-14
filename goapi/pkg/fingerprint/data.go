// Package fingerprint generates Firefox fingerprints for Camoufox.
// It is a focused port of python/src/camoufox/fingerprints.py covering
// the subset Camoufox actually uses: preset selection, font/voice
// subset sampling, and seed generation. Its data files are embedded so the
// binary is self-contained; the ones pythonlib also ships are byte-identical
// copies (data_drift_test.go).
package fingerprint

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed data/fingerprint-presets.json
var rawPresets []byte

//go:embed data/fonts.json
var rawFonts []byte

// Preset is a real fingerprint sample bundled with the library.
// Shape mirrors fingerprint-presets.json entries.
type Preset struct {
	Navigator    PresetNavigator `json:"navigator"`
	Screen       PresetScreen    `json:"screen"`
	WebGL        PresetWebGL     `json:"webgl"`
	Timezone     string          `json:"timezone,omitempty"`
	Fonts        []string        `json:"fonts,omitempty"`
	SpeechVoices []string        `json:"speechVoices,omitempty"`
}

type PresetNavigator struct {
	UserAgent           string `json:"userAgent,omitempty"`
	Platform            string `json:"platform,omitempty"`
	Oscpu               string `json:"oscpu,omitempty"`
	HardwareConcurrency int    `json:"hardwareConcurrency,omitempty"`
	MaxTouchPoints      *int   `json:"maxTouchPoints,omitempty"`
}

type PresetScreen struct {
	Width        int `json:"width,omitempty"`
	Height       int `json:"height,omitempty"`
	AvailWidth   int `json:"availWidth,omitempty"`
	AvailHeight  int `json:"availHeight,omitempty"`
	ColorDepth   int `json:"colorDepth,omitempty"`
	PixelDepth   int `json:"pixelDepth,omitempty"`
}

type PresetWebGL struct {
	UnmaskedVendor   string `json:"unmaskedVendor,omitempty"`
	UnmaskedRenderer string `json:"unmaskedRenderer,omitempty"`
}

type presetsFile struct {
	GeneratedAt string              `json:"generated_at"`
	Version     json.RawMessage     `json:"version"`
	Presets     map[string][]Preset `json:"presets"`
}

var (
	cachedPresets   *presetsFile
	cachedFonts     map[string][]string
)

func loadPresets() (*presetsFile, error) {
	if cachedPresets != nil {
		return cachedPresets, nil
	}
	var p presetsFile
	if err := json.Unmarshal(rawPresets, &p); err != nil {
		return nil, fmt.Errorf("fingerprint: parse presets: %w", err)
	}
	cachedPresets = &p
	return cachedPresets, nil
}

func loadFonts() (map[string][]string, error) {
	if cachedFonts != nil {
		return cachedFonts, nil
	}
	var f map[string][]string
	if err := json.Unmarshal(rawFonts, &f); err != nil {
		return nil, fmt.Errorf("fingerprint: parse fonts: %w", err)
	}
	cachedFonts = f
	return cachedFonts, nil
}

// osKey converts long OS names to the short keys used in fonts.json
// and voices.json ("mac"/"win"/"lin").
func osKey(targetOS string) string {
	switch targetOS {
	case "macos", "mac":
		return "mac"
	case "windows", "win":
		return "win"
	case "linux", "lin":
		return "lin"
	default:
		return "mac"
	}
}

// presetKey converts short OS keys to the long form used in
// fingerprint-presets.json ("macos"/"windows"/"linux").
func presetKey(targetOS string) string {
	switch targetOS {
	case "macos", "mac":
		return "macos"
	case "windows", "win":
		return "windows"
	case "linux", "lin":
		return "linux"
	default:
		return "macos"
	}
}
