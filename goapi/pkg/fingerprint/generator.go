package fingerprint

import (
	"fmt"
	"math/rand/v2"
	"regexp"
	"strings"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// Options drive Generate. Zero value is valid: defaults to a random
// preset across all OSes using a fresh PRNG.
type Options struct {
	// OS restricts presets to one of "windows" | "macos" | "linux".
	// Empty means "any".
	OS string
	// FirefoxVersion, if non-empty, is patched into the preset UA
	// (replaces Firefox/<n> and rv:<n>) — matches from_preset() in
	// pythonlib/camoufox/fingerprints.py.
	FirefoxVersion string
	// Rand controls all sampling. Pass nil for a fresh PRNG seeded
	// from the global source.
	Rand *rand.Rand
}

var ffVersionRE = regexp.MustCompile(`Firefox/\d+\.0`)
var rvVersionRE = regexp.MustCompile(`rv:\d+\.0`)

// Generate samples a preset and writes it onto the provided Config.
// Fields already populated on cfg are not overwritten — preset values
// are applied as defaults. This mirrors merge_into() semantics from
// pythonlib/camoufox/utils.py.
func Generate(cfg *config.Config, opts Options) error {
	rng := opts.Rand
	if rng == nil {
		rng = rand.New(rand.NewPCG(rand.Uint64(), rand.Uint64()))
	}
	preset, err := pickPreset(opts.OS, rng)
	if err != nil {
		return err
	}
	applyPreset(cfg, preset, opts.FirefoxVersion)

	targetOS := osFromPlatform(preset.Navigator.Platform)
	if len(cfg.Fonts) == 0 {
		fonts, err := RandomFontSubset(targetOS, rng)
		if err != nil {
			return err
		}
		cfg.Fonts = fonts
	}
	if len(cfg.Voices) == 0 {
		names, err := RandomVoiceSubset(targetOS, rng)
		if err != nil {
			return err
		}
		voices := make([]config.Voice, len(names))
		for i, n := range names {
			voices[i] = config.Voice{
				VoiceURI:       n,
				Name:           n,
				Lang:           "en-US",
				IsLocalService: true,
				IsDefault:      i == 0,
			}
		}
		cfg.Voices = voices
	}

	// Per-launch fingerprint noise seeds (1..2^32-1; 0 is a no-op
	// signal in the C++ side).
	if cfg.FontsSpacingSeed == nil {
		cfg.FontsSpacingSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
	}
	if cfg.AudioSeed == nil {
		cfg.AudioSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
	}
	if cfg.CanvasSeed == nil {
		cfg.CanvasSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
	}
	// NOTE: window.history.length is deliberately NOT defaulted. Newer
	// Camoufox clamps docShell session history to this value, which
	// disables Page.GoBack/GoForward (see navigation.go). donutbrowser
	// removes this key for the same reason. Callers may still set it
	// explicitly via Config.WindowHistoryLength if they accept that.

	// Rendering-consistency default (matches donutbrowser): suppress
	// OS/theme-dependent chrome styling so canvas/screenshot surfaces do
	// not leak the host theme. Caller-overridable.
	if cfg.DisableTheming == nil {
		cfg.DisableTheming = config.Bool(true)
	}
	return nil
}

func pickPreset(targetOS string, rng *rand.Rand) (*Preset, error) {
	pf, err := loadPresets()
	if err != nil {
		return nil, err
	}
	var bucket []Preset
	if targetOS == "" {
		for _, ps := range pf.Presets {
			bucket = append(bucket, ps...)
		}
	} else {
		bucket = pf.Presets[presetKey(targetOS)]
	}
	if len(bucket) == 0 {
		return nil, fmt.Errorf("fingerprint: no presets for OS %q", targetOS)
	}
	p := bucket[rng.IntN(len(bucket))]
	return &p, nil
}

func applyPreset(cfg *config.Config, p *Preset, ffVersion string) {
	nav := p.Navigator
	if nav.UserAgent != "" && cfg.NavigatorUserAgent == "" {
		ua := nav.UserAgent
		if ffVersion != "" {
			ua = ffVersionRE.ReplaceAllString(ua, "Firefox/"+ffVersion+".0")
			ua = rvVersionRE.ReplaceAllString(ua, "rv:"+ffVersion+".0")
		}
		cfg.NavigatorUserAgent = ua
	}
	if nav.Platform != "" && cfg.NavigatorPlatform == "" {
		cfg.NavigatorPlatform = nav.Platform
	}
	if nav.HardwareConcurrency > 0 && cfg.NavigatorHardwareConcurrency == nil {
		cfg.NavigatorHardwareConcurrency = config.Uint32(uint32(nav.HardwareConcurrency))
	}
	if nav.Oscpu != "" && cfg.NavigatorOscpu == "" {
		cfg.NavigatorOscpu = nav.Oscpu
	} else if nav.Platform != "" && cfg.NavigatorOscpu == "" {
		switch {
		case nav.Platform == "MacIntel":
			cfg.NavigatorOscpu = "Intel Mac OS X 10.15"
		case nav.Platform == "Win32":
			cfg.NavigatorOscpu = "Windows NT 10.0; Win64; x64"
		case strings.Contains(strings.ToLower(nav.Platform), "linux"):
			cfg.NavigatorOscpu = "Linux x86_64"
		}
	}
	if nav.MaxTouchPoints != nil && cfg.NavigatorMaxTouchPoints == nil {
		cfg.NavigatorMaxTouchPoints = config.Uint32(uint32(*nav.MaxTouchPoints))
	}

	scr := p.Screen
	if scr.Width > 0 && cfg.ScreenWidth == nil {
		cfg.ScreenWidth = config.Uint32(uint32(scr.Width))
	}
	if scr.Height > 0 && cfg.ScreenHeight == nil {
		cfg.ScreenHeight = config.Uint32(uint32(scr.Height))
	}
	if scr.ColorDepth > 0 {
		if cfg.ScreenColorDepth == nil {
			cfg.ScreenColorDepth = config.Uint32(uint32(scr.ColorDepth))
		}
		if cfg.ScreenPixelDepth == nil {
			cfg.ScreenPixelDepth = config.Uint32(uint32(scr.ColorDepth))
		}
	}
	if scr.AvailWidth > 0 && cfg.ScreenAvailWidth == nil {
		cfg.ScreenAvailWidth = config.Uint32(uint32(scr.AvailWidth))
	}
	if scr.AvailHeight > 0 && cfg.ScreenAvailHeight == nil {
		cfg.ScreenAvailHeight = config.Uint32(uint32(scr.AvailHeight))
	}

	if p.WebGL.UnmaskedVendor != "" && cfg.WebGLVendor == "" {
		cfg.WebGLVendor = p.WebGL.UnmaskedVendor
	}
	if p.WebGL.UnmaskedRenderer != "" && cfg.WebGLRenderer == "" {
		cfg.WebGLRenderer = p.WebGL.UnmaskedRenderer
	}
	if p.Timezone != "" && cfg.Timezone == "" {
		cfg.Timezone = p.Timezone
	}
}

func osFromPlatform(plat string) string {
	switch {
	case plat == "MacIntel":
		return "macos"
	case plat == "Win32":
		return "windows"
	case strings.Contains(strings.ToLower(plat), "linux"):
		return "linux"
	default:
		return "macos"
	}
}
