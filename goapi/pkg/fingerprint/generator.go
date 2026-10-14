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
	// python/src/camoufox/fingerprints.py.
	FirefoxVersion string
	// Rand controls all sampling. Pass nil for a fresh PRNG seeded
	// from the global source.
	Rand *rand.Rand
	// HostOS is the machine the browser runs on ("windows" | "macos" |
	// "linux"; config.HostOS). An identity of the host's own macOS or Windows
	// is native: the browser renders the real system fonts, so only that OS's
	// essential fonts are claimed.
	HostOS string
}

var ffVersionRE = regexp.MustCompile(`Firefox/\d+\.0`)
var rvVersionRE = regexp.MustCompile(`rv:\d+\.0`)

// applyWindow mirrors follow_baseline_protection and clamp_window_dimensions
// (python/src/camoufox/fingerprints.py): claim the available screen and touch
// points the browser will report, then fit a maximised window inside that
// screen. Presets carry no window size, and without this the browser keeps
// browser-init.patch's 1280x1040 on any screen (#166). Inner is left to the
// browser, which lays it out inside the real window.
func applyWindow(cfg *config.Config, targetOS string) {
	if cfg.ScreenWidth != nil && cfg.ScreenHeight != nil {
		// The browser's baseline protection (nsRFPService) reports the whole
		// screen less a fixed taskbar for the claimed OS.
		aw, ah := *cfg.ScreenWidth, *cfg.ScreenHeight-launcher.BaselineTaskbarHeight[osKey(targetOS)]
		cfg.ScreenAvailWidth, cfg.ScreenAvailHeight = config.Uint32(aw), config.Uint32(ah)
		if cfg.WindowOuterWidth == nil || *cfg.WindowOuterWidth > aw {
			cfg.WindowOuterWidth = config.Uint32(aw)
		}
		if cfg.WindowOuterHeight == nil || *cfg.WindowOuterHeight > ah {
			cfg.WindowOuterHeight = config.Uint32(ah)
		}
	}
	if p := cfg.NavigatorMaxTouchPoints; p != nil && *p > 1 {
		cfg.NavigatorMaxTouchPoints = config.Uint32(launcher.BaselineMultiTouchPoints)
	}
}

// Generate samples a preset and writes it onto the provided Config.
// Fields already populated on cfg are not overwritten — preset values
// are applied as defaults. This mirrors merge_into() semantics from
// python/src/camoufox/utils.py.
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
	applyWindow(cfg, targetOS)
	// Mirrors python/src/camoufox/utils.py:1675: the block is pinned explicitly, so
	// an empty voice list (linux ships none) cannot fall through to the host's
	// native voices (#166).
	if cfg.VoicesBlockIfNotDefined == nil {
		cfg.VoicesBlockIfNotDefined = config.Bool(true)
	}
	if len(cfg.Fonts) == 0 {
		native := targetOS == opts.HostOS && targetOS != "linux"
		fonts, err := RandomFontSubset(targetOS, native, rng)
		if err != nil {
			return err
		}
		cfg.Fonts = fonts
	}
	if len(cfg.Voices) == 0 {
		// Drawn after the locale is known: the Windows list is the display
		// language's pack, so an fr-FR identity has French voices.
		locale := cfg.NavigatorLanguage
		if cfg.LocaleLanguage != "" {
			locale = cfg.LocaleLanguage
			if cfg.LocaleRegion != "" {
				locale += "-" + cfg.LocaleRegion
			}
		}
		voices, err := RandomVoices(targetOS, locale, rng)
		if err != nil {
			return err
		}
		cfg.Voices = voices
	}

	// Per-launch fingerprint noise seeds (1..2^32-1; 0 is a no-op
	// signal in the C++ side).
	if cfg.AudioSeed == nil {
		cfg.AudioSeed = config.Uint32(uint32(1 + rng.Uint32N(0xFFFFFFFE)))
	}

	// Rendering-consistency default (matches donutbrowser): suppress
	// OS/theme-dependent chrome styling so canvas/screenshot surfaces do
	// not leak the host theme. Caller-overridable.
	if cfg.DisableTheming == nil {
		cfg.DisableTheming = config.Bool(true)
	}

	// Per-OS media codec matrix (#6): keep canPlayType / isTypeSupported /
	// decodingInfo coherent with the spoofed OS instead of leaking the host's
	// real decoder support.
	if len(cfg.MediaCanPlayType) == 0 && len(cfg.MediaDecodingInfo) == 0 {
		cfg.MediaCanPlayType, cfg.MediaDecodingInfo = mediaCodecProfile(targetOS)
	}

	// CSS media features (#8): default to the low-entropy "blends" values so a
	// wide-gamut/HDR monitor and host accessibility settings don't leak; pick
	// prefers-color-scheme per-profile so instances don't all report one theme.
	if cfg.CSSColorGamut == "" {
		cfg.CSSColorGamut = "srgb"
	}
	if cfg.CSSDynamicRange == "" {
		cfg.CSSDynamicRange = "standard"
	}
	if cfg.CSSPrefersColorScheme == "" {
		if rng.IntN(2) == 0 {
			cfg.CSSPrefersColorScheme = "light"
		} else {
			cfg.CSSPrefersColorScheme = "dark"
		}
	}

	// screen.orientation (#20): derive from the spoofed dimensions so the real
	// host orientation doesn't leak. Desktop presets are landscape (width >=
	// height) → landscape-primary; angle 0 for the primary orientation.
	if cfg.ScreenOrientation == "" {
		cfg.ScreenOrientation = "landscape-primary"
		if cfg.ScreenWidth != nil && cfg.ScreenHeight != nil && *cfg.ScreenHeight > *cfg.ScreenWidth {
			cfg.ScreenOrientation = "portrait-primary"
		}
	}
	if cfg.ScreenOrientationAngle == nil {
		cfg.ScreenOrientationAngle = config.Uint32(0)
	}
	return nil
}

// mediaCodecProfile returns the per-OS answers for OS-distinguishing media
// codecs, keyed by the codec substring matched in a queried media type. HEVC
// (hvc1/hev1) is decodable in Firefox on Windows/macOS via the system decoder
// but not on Linux, so a cross-OS profile must spoof it consistently across
// canPlayType, isTypeSupported, and decodingInfo.
func mediaCodecProfile(targetOS string) (map[string]string, map[string]config.MediaDecodeInfo) {
	hevc := targetOS == "windows" || targetOS == "macos"
	canPlay := make(map[string]string, 2)
	dec := make(map[string]config.MediaDecodeInfo, 2)
	for _, c := range []string{"hvc1", "hev1"} {
		if hevc {
			canPlay[c] = "probably"
			dec[c] = config.MediaDecodeInfo{Supported: true, Smooth: true, PowerEfficient: true}
		} else {
			canPlay[c] = ""
			dec[c] = config.MediaDecodeInfo{Supported: false}
		}
	}
	return canPlay, dec
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
