package fingerprint

import (
	"math/rand/v2"
	"testing"

	"github.com/lang315/camoufox/goapi/pkg/config"
)

// #166: goapi left window.outer* unset, so browser-init.patch kept 1280x1040
// on any screen. Every draw must satisfy outer <= avail <= screen, with a
// visible taskbar (avail height < screen height).
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
			if !(ow <= aw && aw <= sw && oh <= ah && ah < sh) {
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
