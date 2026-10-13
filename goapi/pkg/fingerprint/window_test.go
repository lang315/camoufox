package fingerprint

import (
	"math/rand/v2"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// #166: goapi left window.outer* unset, so browser-init.patch kept 1280x1040
// on any screen. The browser reports the available screen as the whole screen
// less the claimed OS's baseline taskbar (follow_baseline_protection in
// pythonlib), so every draw must claim exactly that and fit the window inside
// it. The old 40/25/27 taskbars put a go-macos window 51 px below the reported
// avail (e2e run 38413736022).
func TestGeneratedWindowFitsScreen(t *testing.T) {
	for _, osKey := range []string{"windows", "macos", "linux"} {
		rng := rand.New(rand.NewPCG(1, 2))
		for i := 0; i < 300; i++ {
			cfg := &config.Config{}
			if err := Generate(cfg, Options{OS: osKey, Rand: rng}); err != nil {
				t.Fatal(err)
			}
			sw, sh := *cfg.ScreenWidth, *cfg.ScreenHeight
			aw, ah := *cfg.ScreenAvailWidth, *cfg.ScreenAvailHeight
			if cfg.WindowOuterWidth == nil || cfg.WindowOuterHeight == nil {
				t.Fatalf("%s draw %d: window.outer* unset", osKey, i)
			}
			ow, oh := *cfg.WindowOuterWidth, *cfg.WindowOuterHeight
			if !(ow <= aw && aw == sw && oh <= ah && ah == sh-baselineTaskbarHeight[osKey]) {
				t.Fatalf("%s draw %d: screen %dx%d avail %dx%d outer %dx%d", osKey, i, sw, sh, aw, ah, ow, oh)
			}
		}
	}
}

// #166: with no voices for linux and no block flag, the browser registered
// the host's own voices (Microsoft voices on a Windows host).
func TestGenerateAlwaysBlocksHostVoices(t *testing.T) {
	for _, osKey := range []string{"windows", "macos", "linux"} {
		cfg := &config.Config{}
		if err := Generate(cfg, Options{OS: osKey, Rand: rand.New(rand.NewPCG(3, 4))}); err != nil {
			t.Fatal(err)
		}
		if cfg.VoicesBlockIfNotDefined == nil || !*cfg.VoicesBlockIfNotDefined {
			t.Fatalf("%s: voices:blockIfNotDefined not set", osKey)
		}
	}
}

// pythonlib's follow_baseline_protection: more than one touch point reads as 5
// in the browser, so the identity must claim 5.
func TestGeneratedTouchPointsFollowBaseline(t *testing.T) {
	for _, osKey := range []string{"windows", "macos", "linux"} {
		rng := rand.New(rand.NewPCG(5, 6))
		for i := 0; i < 300; i++ {
			cfg := &config.Config{}
			if err := Generate(cfg, Options{OS: osKey, Rand: rng}); err != nil {
				t.Fatal(err)
			}
			if p := cfg.NavigatorMaxTouchPoints; p != nil && *p > 1 && *p != baselineMultiTouchPoints {
				t.Fatalf("%s draw %d: maxTouchPoints %d, the browser reports %d", osKey, i, *p, baselineMultiTouchPoints)
			}
		}
	}
}
