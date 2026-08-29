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
	// fonts:whitelist is a separate, wider key from Fonts above (see
	// LaunchFontWhitelist doc comment): it is the launch-time whitelist that
	// keeps every bundled OS's families alive at startup, while Fonts stays
	// this profile's random per-OS subset.
	if len(cfg.FontsWhitelist) == 0 {
		whitelist, err := LaunchFontWhitelist()
		if err != nil {
			return err
		}
		cfg.FontsWhitelist = whitelist
	}
	if len(cfg.Voices) == 0 {
		names, err := RandomVoiceSubset(targetOS, rng)
		if err != nil {
			return err
		}
		meta := voiceMetaFor(targetOS)
		voices := make([]config.Voice, len(names))
		for i, n := range names {
			lang, local := "en-US", true
			if m, ok := meta[n]; ok {
				lang, local = m.lang, m.local
			}
			voices[i] = config.Voice{
				VoiceURI:       n,
				Name:           n,
				Lang:           lang,
				IsLocalService: local,
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
