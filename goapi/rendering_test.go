package camoufox

import (
	"math/rand/v2"
	"strings"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// #196: pythonlib's plan_rendering covers the canvas of an identity that names
// a GPU, which every goapi identity does, and sends no seed under the cover.
func TestCanvasIsCoveredUnlessTheCallerOptsOut(t *testing.T) {
	off := false
	for _, c := range []struct {
		placeholder *bool
		cover       bool
	}{{nil, true}, {&off, false}} {
		cfg := &config.Config{}
		seedUncoveredCanvas(cfg, c.placeholder, rand.New(rand.NewPCG(1, 2)))
		if got := coversCanvas(c.placeholder); got != c.cover {
			t.Fatalf("placeholder %v: covered %v, want %v", c.placeholder, got, c.cover)
		}
		if (cfg.CanvasSeed != nil) == c.cover {
			t.Fatalf("placeholder %v: canvas seed %v under cover %v", c.placeholder, cfg.CanvasSeed, c.cover)
		}
	}
}

func TestCanvasPlaceholderKeepsTheCallersOverrides(t *testing.T) {
	prefs := map[string]any{baselineOverridesPref: "+Foo,,-Bar"}
	addCanvasPlaceholder(prefs)
	want := "+Foo,-Bar," + strings.Join(canvasPlaceholderTargets, ",")
	if got := prefs[baselineOverridesPref]; got != want {
		t.Fatalf("overrides = %q, want %q", got, want)
	}
}

// set_webgpu with no host GPU: WebGPU where Firefox has it, with no adapter.
func TestWebGPUFollowsTheClaimedDeviceAndBlocksTheHostAdapter(t *testing.T) {
	for _, c := range []struct {
		os, vendor string
		enabled    bool
	}{
		{"windows", "Google Inc. (NVIDIA)", true},
		{"macos", "Apple", true},
		{"macos", "Intel Inc.", false},
		{"linux", "Mesa", false},
	} {
		prefs := map[string]any{}
		setWebGPU(prefs, c.os, c.vendor)
		if prefs["dom.webgpu.enabled"] != c.enabled {
			t.Fatalf("%s %s: dom.webgpu.enabled = %v", c.os, c.vendor, prefs["dom.webgpu.enabled"])
		}
		if _, blocked := prefs[webgpuBlocklistPref]; blocked != c.enabled {
			t.Fatalf("%s %s: %s set %v", c.os, c.vendor, webgpuBlocklistPref, blocked)
		}
	}
	prefs := map[string]any{"dom.webgpu.enabled": true, webgpuBlocklistPref: 1}
	setWebGPU(prefs, "linux", "")
	if prefs[webgpuBlocklistPref] != 1 {
		t.Fatal("a caller's WebGPU status was overwritten")
	}
}

func TestCoveredCanvasWarns(t *testing.T) {
	if w := leakWarnings(&config.Config{}, false, false, true); len(w) != 1 || !strings.Contains(w[0], "WithCanvasPlaceholder(false)") {
		t.Fatalf("covered canvas warnings = %q", w)
	}
}
