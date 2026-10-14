package camoufox

import (
	"math/rand/v2"
	"strings"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// The rendering plan, as python/src/camoufox/utils.py plan_rendering and
// host_rendering.py decide it (#196). A page reads canvas and WebGL pixels the
// host renders, whatever the identity claims, so only an identity claiming the
// host's own OS and GPU agrees with them. goapi identities always name a
// preset's GPU, which plan_rendering covers: canvas readback becomes
// privacy.resistFingerprinting's random placeholder and no noise seed is sent.
// WithCanvasPlaceholder(false) keeps the host canvas with the fork's seeded
// noise instead (pythonlib's canvas_noise=False).

const (
	baselineOverridesPref = "privacy.baselineFingerprintingProtection.overrides"
	webgpuBlocklistPref   = "gfx.blacklist.webgpu"
	// nsIGfxInfo statuses (widget/GfxInfoFeatureStatusDefs.inc). A blocked device
	// resolves requestAdapter() to null.
	featureBlockedDevice = 4
)

// The canvas targets privacy.resistFingerprinting turns on, and only those.
var canvasPlaceholderTargets = []string{
	"+CanvasImageExtractionPrompt",
	"+CanvasExtractionBeforeUserInputIsBlocked",
	"+CanvasExtractionFromThirdPartiesIsBlocked",
}

// coversCanvas reports whether the launch turns on the canvas placeholder.
func coversCanvas(placeholder *bool) bool {
	return placeholder == nil || *placeholder
}

// seedUncoveredCanvas draws the fork's canvas noise seed (canvas-spoofing.patch)
// for a launch that leaves the canvas uncovered; under the placeholder the seed
// is inert, so none is sent.
func seedUncoveredCanvas(cfg *config.Config, placeholder *bool, rng *rand.Rand) {
	if coversCanvas(placeholder) || cfg.CanvasSeed != nil {
		return
	}
	n := rand.Uint32N(0xFFFFFFFE)
	if rng != nil {
		n = rng.Uint32N(0xFFFFFFFE)
	}
	cfg.CanvasSeed = config.Uint32(1 + n)
}

// addCanvasPlaceholder is add_canvas_placeholder: turn the targets on, keeping
// any baseline overrides already set.
func addCanvasPlaceholder(prefs map[string]any) {
	var overrides []string
	if s, _ := prefs[baselineOverridesPref].(string); s != "" {
		for _, o := range strings.Split(s, ",") {
			if o != "" {
				overrides = append(overrides, o)
			}
		}
	}
	prefs[baselineOverridesPref] = strings.Join(append(overrides, canvasPlaceholderTargets...), ",")
}

// setWebGPU is set_webgpu with no host GPU: Firefox enables WebGPU on Windows
// and on Apple Silicon Macs only, and the host's adapter belongs to the host's
// GPU, which a preset's GPU is not known to be, so requestAdapter() resolves
// to null, as Windows Firefox does on a blocked device. Prefs the caller set
// are kept.
func setWebGPU(prefs map[string]any, targetOS, webglVendor string) {
	if _, set := prefs["dom.webgpu.enabled"]; !set {
		prefs["dom.webgpu.enabled"] = targetOS == "windows" || (targetOS == "macos" && webglVendor == "Apple")
	}
	if on, _ := prefs["dom.webgpu.enabled"].(bool); on {
		if _, set := prefs[webgpuBlocklistPref]; !set {
			prefs[webgpuBlocklistPref] = featureBlockedDevice
		}
	}
}
