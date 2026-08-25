package camoufox

import (
	"math/rand/v2"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/config"
	"github.com/lang315/camoufox/goapi/pkg/fingerprint"
	"github.com/lang315/camoufox/goapi/pkg/proxy"
)

// launchConfig is the internal accumulation point for functional
// options. Fields are populated by With* functions and consumed by
// Launch.
type launchConfig struct {
	executablePath  string
	headless        bool
	debug           bool
	args            []string
	env             []string
	firefoxUserPrefs map[string]any
	virtualDisplay  string
	userDataDir     string

	os             string
	firefoxVersion string
	rand           *rand.Rand

	customFingerprint bool // disables auto preset injection
	skipFingerprint   bool
	cfg               *config.Config

	keepMDNSObfuscation bool // opt out of Phase-5 mDNS disable

	proxy        *proxy.Proxy
	geoIPEnabled bool
	geoIPTimeout time.Duration

	addons []string
}

// Option mutates a launchConfig. Pass to Launch.
type Option func(*launchConfig)

// WithExecutablePath sets the path to the Camoufox firefox binary.
// Required.
func WithExecutablePath(path string) Option {
	return func(c *launchConfig) { c.executablePath = path }
}

// WithHeadless toggles --headless on the browser CLI.
func WithHeadless(b bool) Option { return func(c *launchConfig) { c.headless = b } }

// WithOS biases preset selection to the named OS
// ("windows" | "macos" | "linux"). Empty means any.
func WithOS(os string) Option { return func(c *launchConfig) { c.os = os } }

// WithFirefoxVersion patches Firefox/<n>.0 and rv:<n>.0 in the
// preset's UA. Useful when the bundled Camoufox version differs from
// the preset's.
func WithFirefoxVersion(v string) Option { return func(c *launchConfig) { c.firefoxVersion = v } }

// WithRand supplies a deterministic PRNG. Skip for default
// crypto-seeded behavior.
func WithRand(r *rand.Rand) Option { return func(c *launchConfig) { c.rand = r } }

// WithConfig injects a fully-formed CAMOU_CONFIG payload. Any
// fingerprint generation done later applies as defaults on top.
func WithConfig(cfg *config.Config) Option { return func(c *launchConfig) { c.cfg = cfg } }

// WithNoFingerprint disables automatic preset injection. Use when the
// caller has populated the Config manually.
func WithNoFingerprint() Option { return func(c *launchConfig) { c.skipFingerprint = true } }

// WithProxy routes browser traffic through the given proxy.
func WithProxy(p proxy.Proxy) Option {
	return func(c *launchConfig) {
		pp := p
		c.proxy = &pp
	}
}

// WithGeoIP, when enabled, queries ip-api.com through the proxy to
// resolve timezone, locale, and WebRTC IP, populating matching fields
// on the Config before launch.
func WithGeoIP(enable bool) Option { return func(c *launchConfig) { c.geoIPEnabled = enable } }

// WithGeoIPTimeout caps the geo-resolution HTTP call (default 8s).
func WithGeoIPTimeout(d time.Duration) Option {
	return func(c *launchConfig) { c.geoIPTimeout = d }
}

// WithFingerprintOverride applies the supplied Options on top of the
// auto-generated fingerprint.
func WithFingerprintOverride(o fingerprint.Options) Option {
	return func(c *launchConfig) {
		c.os = o.OS
		c.firefoxVersion = o.FirefoxVersion
		c.rand = o.Rand
		c.customFingerprint = true
	}
}

// WithArgs appends raw firefox CLI args. The --juggler-pipe,
// --headless and -profile flags are managed by Launch and should not
// be passed here.
//
// Passing -profile or --profile is rejected by Launch rather than
// ignored. Launch prepends its own and Firefox honors the FIRST
// occurrence (measured -- with two -profile flags only the first
// directory is populated), so a caller-supplied one would never take
// effect, and the profile Firefox did use would be deleted on Close.
// Use WithUserDataDir to run against a specific profile directory.
func WithArgs(args ...string) Option {
	return func(c *launchConfig) { c.args = append(c.args, args...) }
}

// WithEnv appends additional environment entries in "KEY=VALUE" form.
func WithEnv(env ...string) Option {
	return func(c *launchConfig) { c.env = append(c.env, env...) }
}

// WithFirefoxUserPref sets a Firefox about:config preference. Multiple
// calls accumulate.
func WithFirefoxUserPref(name string, value any) Option {
	return func(c *launchConfig) {
		if c.firefoxUserPrefs == nil {
			c.firefoxUserPrefs = make(map[string]any)
		}
		c.firefoxUserPrefs[name] = value
	}
}

// WithDebug enables verbose logging from the goapi launcher and
// passes --debug to the browser via CAMOU_CONFIG.debug.
func WithDebug(b bool) Option { return func(c *launchConfig) { c.debug = b } }

// WithVirtualDisplay points the browser at an X11 display
// (e.g. ":99"). Useful on Linux with Xvfb running headfully.
func WithVirtualDisplay(display string) Option {
	return func(c *launchConfig) { c.virtualDisplay = display }
}

// WithUserDataDir runs the browser against a caller-owned profile directory
// instead of a throwaway one. State (cookies, localStorage, prefs) then
// persists across launches, and goapi never deletes the directory.
//
// Without this, each Launch gets a fresh temp profile that Close removes.
// That default exists because a shared profile links sessions that callers
// expect to be independent -- see issue #50.
func WithUserDataDir(dir string) Option {
	return func(c *launchConfig) { c.userDataDir = dir }
}

// WithAddons supplies a list of paths to unpacked Firefox extensions.
func WithAddons(paths ...string) Option {
	return func(c *launchConfig) { c.addons = append(c.addons, paths...) }
}

// WithCanvasNoise tunes the canvas pixel-perturbation pipeline added
// by patches/canvas-spoofing.patch. density is the fraction of RGB
// channels touched per readback (default 0.0005 = 1 in 2000); strength
// is the absolute LSB delta (default 1). Larger values produce visible
// banding in headful mode — Brave's low-impact default is the safe
// starting point.
func WithCanvasNoise(density float64, strengthLSB uint32) Option {
	return func(c *launchConfig) {
		if c.cfg == nil {
			c.cfg = &config.Config{}
		}
		c.cfg.CanvasNoiseDensity = config.Float64(density)
		c.cfg.CanvasNoiseStrength = config.Uint32(strengthLSB)
	}
}

// WithMDNSObfuscation re-enables Firefox's mDNS host-address
// obfuscation (`media.peerconnection.ice.obfuscate_host_addresses`).
//
// Default since Phase 5 is **false** — Camoufox disables this pref so
// the C++ regex in webrtc-ip-spoofing.patch catches every host
// candidate uniformly instead of letting them pass as `<uuid>.local`
// hostnames. Real-WebRTC callers that negotiate against peers expecting
// mDNS connectivity should call this with `true` to restore Firefox's
// native behavior.
func WithMDNSObfuscation(enable bool) Option {
	return func(c *launchConfig) { c.keepMDNSObfuscation = enable }
}

// WithWebRTCLocalIP wires the dead config keys webrtc:localipv4 /
// webrtc:localipv6 from patches/webrtc-ip-spoofing2.patch. When set,
// RFC1918 / ULA candidates in SDP are replaced with the supplied local
// addresses instead of falling back to the public spoof. Pass empty
// strings to leave a slot unset.
func WithWebRTCLocalIP(ipv4, ipv6 string) Option {
	return func(c *launchConfig) {
		if c.cfg == nil {
			c.cfg = &config.Config{}
		}
		if ipv4 != "" {
			c.cfg.WebRTCLocalIPv4 = ipv4
		}
		if ipv6 != "" {
			c.cfg.WebRTCLocalIPv6 = ipv6
		}
	}
}
