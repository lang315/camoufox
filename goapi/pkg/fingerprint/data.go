// Package fingerprint generates Firefox fingerprints for Camoufox.
// It is a focused port of pythonlib/camoufox/fingerprints.py covering
// the subset Camoufox actually uses: preset selection, font/voice
// subset sampling, and seed generation. The four data files (presets,
// fonts, voices, browserforge mapping) are embedded so the binary is
// self-contained.
package fingerprint

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
)

//go:embed data/fingerprint-presets.json
var rawPresets []byte

//go:embed data/fonts.json
var rawFonts []byte

//go:embed data/voices.json
var rawVoices []byte

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
	cachedVoices    map[string][]string
	cachedVoiceMeta map[string]map[string]voiceMeta
)

// voiceMeta carries the per-voice attributes that must stay coherent with
// the claimed OS: a macOS "Alice" voice is it-IT, not en-US.
type voiceMeta struct {
	lang  string
	local bool
}

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

// loadVoices returns voice *names* per OS key ("win"/"mac"/"lin").
// Original entries are formatted "Name:locale:type". It also populates
// cachedVoiceMeta so callers can recover each voice's true lang/localService
// (see voiceMetaFor) instead of stamping a hardcoded en-US on every voice.
func loadVoices() (map[string][]string, error) {
	if cachedVoices != nil {
		return cachedVoices, nil
	}
	var raw map[string][]string
	if err := json.Unmarshal(rawVoices, &raw); err != nil {
		return nil, fmt.Errorf("fingerprint: parse voices: %w", err)
	}
	names := make(map[string][]string, len(raw))
	meta := make(map[string]map[string]voiceMeta, len(raw))
	for k, entries := range raw {
		ns := make([]string, 0, len(entries))
		mm := make(map[string]voiceMeta, len(entries))
		for _, e := range entries {
			name, lang, local := parseVoiceEntry(e)
			if name == "" {
				continue
			}
			ns = append(ns, name)
			mm[name] = voiceMeta{lang: lang, local: local}
		}
		names[k] = ns
		meta[k] = mm
	}
	cachedVoices = names
	cachedVoiceMeta = meta
	return cachedVoices, nil
}

// parseVoiceEntry splits a "Name:lang:type" entry. The name can itself be
// empty of colons, so the lang/type are parsed from the right and everything
// before is the name. Real Firefox exposes only local voices, so a non-"local"
// type maps to isLocalService=false. Defaults: en-US, local.
func parseVoiceEntry(e string) (name, lang string, local bool) {
	last := strings.LastIndexByte(e, ':')
	if last < 0 {
		return e, "en-US", true
	}
	typ := e[last+1:]
	rest := e[:last]
	second := strings.LastIndexByte(rest, ':')
	if second < 0 {
		return rest, typ, true // single colon: "Name:lang"
	}
	return rest[:second], rest[second+1:], typ != "remote"
}

// voiceMetaFor returns name→{lang,local} for an OS, loading voices on demand.
func voiceMetaFor(targetOS string) map[string]voiceMeta {
	if cachedVoiceMeta == nil {
		_, _ = loadVoices()
	}
	return cachedVoiceMeta[osKey(targetOS)]
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
