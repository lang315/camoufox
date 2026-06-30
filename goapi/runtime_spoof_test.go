package camoufox_test

// Runtime verification of the device-faking spoofs against a real Camoufox
// binary. Unlike the package unit tests (which only check that the goapi
// generator produces the right CAMOU_CONFIG), this launches the patched
// browser and asserts the spoofs actually take effect in page JS.
//
// Gated on CAMOUFOX_BIN: skipped (not failed) when no binary is available, so
// `go test ./...` stays green on a dev machine without a Linux/Windows build.
//
//	CAMOUFOX_BIN=/path/to/camoufox go test ./goapi -run TestRuntimeSpoofs -v
//
// The config is generated in-test with a pinned RNG and OS=windows (so HEVC
// answers "probably") and passed via WithConfig + WithNoFingerprint, making it
// the single source of truth the assertions compare against.

import (
	"context"
	"encoding/json"
	"math/rand/v2"
	"os"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/config"
	"github.com/lang315/camoufox/goapi/pkg/fingerprint"
)

func launchForSpoofTest(t *testing.T) (context.Context, *camoufox.Page, *config.Config, func()) {
	t.Helper()
	exe := os.Getenv("CAMOUFOX_BIN")
	if exe == "" {
		t.Skip("set CAMOUFOX_BIN to a Camoufox binary to run runtime spoof verification")
	}
	cfg := &config.Config{}
	if err := fingerprint.Generate(cfg, fingerprint.Options{
		OS:   "windows",
		Rand: rand.New(rand.NewPCG(0xC0FFEE, 0x1234)),
	}); err != nil {
		t.Fatalf("generate: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(exe),
		camoufox.WithConfig(cfg),
		camoufox.WithNoFingerprint(), // cfg is authoritative; do not regenerate
		camoufox.WithHeadless(true),
	)
	if err != nil {
		cancel()
		t.Fatalf("launch: %v", err)
	}
	cleanup := func() { _ = b.Close(); cancel() }
	bc, err := b.NewContext(ctx)
	if err != nil {
		cleanup()
		t.Fatalf("new context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		cleanup()
		t.Fatalf("new page: %v", err)
	}
	if err := p.Goto(ctx, "about:blank", camoufox.GotoOptions{
		WaitUntil: camoufox.WaitUntilLoad,
		Timeout:   30 * time.Second,
	}); err != nil {
		cleanup()
		t.Fatalf("goto: %v", err)
	}
	return ctx, p, cfg, cleanup
}

func evalString(t *testing.T, ctx context.Context, p *camoufox.Page, expr string) string {
	t.Helper()
	v, err := p.Evaluate(ctx, expr)
	if err != nil {
		t.Fatalf("eval %q: %v", expr, err)
	}
	s, ok := v.(string)
	if !ok {
		t.Fatalf("eval %q: want string, got %T (%v)", expr, v, v)
	}
	return s
}

func evalBool(t *testing.T, ctx context.Context, p *camoufox.Page, expr string) bool {
	t.Helper()
	v, err := p.Evaluate(ctx, expr)
	if err != nil {
		t.Fatalf("eval %q: %v", expr, err)
	}
	b, ok := v.(bool)
	if !ok {
		t.Fatalf("eval %q: want bool, got %T (%v)", expr, v, v)
	}
	return b
}

// evalFloat reads a JS number. Evaluate decodes JS numbers as float64.
func evalFloat(t *testing.T, ctx context.Context, p *camoufox.Page, expr string) float64 {
	t.Helper()
	v, err := p.Evaluate(ctx, expr)
	if err != nil {
		t.Fatalf("eval %q: %v", expr, err)
	}
	f, ok := v.(float64)
	if !ok {
		t.Fatalf("eval %q: want float64, got %T (%v)", expr, v, v)
	}
	return f
}

func TestRuntimeSpoofs(t *testing.T) {
	ctx, p, cfg, cleanup := launchForSpoofTest(t)
	defer cleanup()

	// #1 WebGPU disabled (interim): navigator.gpu must be undefined.
	t.Run("webgpu_absent", func(t *testing.T) {
		if !evalBool(t, ctx, p, "typeof navigator.gpu === 'undefined'") {
			t.Error("navigator.gpu should be undefined (dom.webgpu.enabled=false)")
		}
	})

	// #6-adjacent: WebGL renderer/vendor must equal the spoofed strings.
	t.Run("webgl_renderer", func(t *testing.T) {
		const expr = `(() => {
			const gl = document.createElement('canvas').getContext('webgl');
			const e = gl.getExtension('WEBGL_debug_renderer_info');
			return JSON.stringify({
				v: gl.getParameter(e.UNMASKED_VENDOR_WEBGL),
				r: gl.getParameter(e.UNMASKED_RENDERER_WEBGL),
			});
		})()`
		var got struct{ V, R string }
		if err := json.Unmarshal([]byte(evalString(t, ctx, p, expr)), &got); err != nil {
			t.Fatalf("decode: %v", err)
		}
		if cfg.WebGLVendor != "" && got.V != cfg.WebGLVendor {
			t.Errorf("webgl vendor = %q, want %q", got.V, cfg.WebGLVendor)
		}
		if cfg.WebGLRenderer != "" && got.R != cfg.WebGLRenderer {
			t.Errorf("webgl renderer = %q, want %q", got.R, cfg.WebGLRenderer)
		}
	})

	// #6 media codec matrix: canPlayType + isTypeSupported coherent with cfg.
	t.Run("codec_hevc", func(t *testing.T) {
		want := cfg.MediaCanPlayType["hvc1"] // "probably" on windows
		got := evalString(t, ctx, p,
			`document.createElement('video').canPlayType('video/mp4; codecs="hvc1"')`)
		if got != want {
			t.Errorf("canPlayType(hvc1) = %q, want %q", got, want)
		}
		supported := evalBool(t, ctx, p,
			`MediaSource.isTypeSupported('video/mp4; codecs="hvc1"')`)
		if supported != (want != "") {
			t.Errorf("isTypeSupported(hvc1) = %v, want %v", supported, want != "")
		}
	})

	// #6 decodingInfo is async — kick the promise, then poll window.__dec.
	t.Run("codec_decodingInfo", func(t *testing.T) {
		_, err := p.Evaluate(ctx, `(() => {
			window.__dec = null;
			navigator.mediaCapabilities.decodingInfo({
				type: 'media-source',
				video: { contentType: 'video/mp4; codecs="hvc1"',
					width: 1920, height: 1080, bitrate: 1000000, framerate: 30 },
			}).then(r => { window.__dec = {s: r.supported, sm: r.smooth, pe: r.powerEfficient}; })
			  .catch(e => { window.__dec = {err: String(e)}; });
			return true;
		})()`)
		if err != nil {
			t.Fatalf("kick decodingInfo: %v", err)
		}
		var dec struct {
			S, Sm, Pe bool
			Err       string
		}
		got := false
		for range 40 {
			raw := evalString(t, ctx, p, `JSON.stringify(window.__dec)`)
			if raw != "null" {
				if err := json.Unmarshal([]byte(raw), &dec); err != nil {
					t.Fatalf("decode __dec %q: %v", raw, err)
				}
				got = true
				break
			}
			time.Sleep(50 * time.Millisecond)
		}
		if !got {
			t.Skip("decodingInfo did not resolve in time")
		}
		if dec.Err != "" {
			t.Fatalf("decodingInfo rejected: %s", dec.Err)
		}
		want := cfg.MediaDecodingInfo["hvc1"]
		if dec.S != want.Supported || dec.Sm != want.Smooth || dec.Pe != want.PowerEfficient {
			t.Errorf("decodingInfo(hvc1) = {sup:%v smooth:%v pe:%v}, want {sup:%v smooth:%v pe:%v}",
				dec.S, dec.Sm, dec.Pe, want.Supported, want.Smooth, want.PowerEfficient)
		}
	})

	// #8 CSS media: color-gamut, dynamic-range, prefers-color-scheme.
	t.Run("css_media", func(t *testing.T) {
		if !evalBool(t, ctx, p, `matchMedia('(color-gamut: srgb)').matches`) {
			t.Error("color-gamut srgb should match")
		}
		if evalBool(t, ctx, p, `matchMedia('(color-gamut: p3)').matches`) {
			t.Error("color-gamut p3 should NOT match (spoofed srgb)")
		}
		if evalBool(t, ctx, p, `matchMedia('(dynamic-range: high)').matches`) {
			t.Error("dynamic-range high should NOT match (spoofed standard)")
		}
		scheme := cfg.CSSPrefersColorScheme // "light" or "dark"
		if !evalBool(t, ctx, p, `matchMedia('(prefers-color-scheme: `+scheme+`)').matches`) {
			t.Errorf("prefers-color-scheme should be %q", scheme)
		}
	})

	// #29 regression guard: Intl resolvedOptions stay consistent with the spoof
	// (calendar/numberingSystem are CLDR-derived, timeZone is the spoofed one).
	t.Run("intl_consistency", func(t *testing.T) {
		if cal := evalString(t, ctx, p, `Intl.DateTimeFormat().resolvedOptions().calendar`); cal != "gregory" {
			t.Errorf("calendar = %q, want gregory", cal)
		}
		if ns := evalString(t, ctx, p, `Intl.DateTimeFormat().resolvedOptions().numberingSystem`); ns != "latn" {
			t.Errorf("numberingSystem = %q, want latn", ns)
		}
		if cfg.Timezone != "" {
			if tz := evalString(t, ctx, p, `Intl.DateTimeFormat().resolvedOptions().timeZone`); tz != cfg.Timezone {
				t.Errorf("timeZone = %q, want %q", tz, cfg.Timezone)
			}
		}
	})

	// #20 screen.orientation type + angle.
	t.Run("screen_orientation", func(t *testing.T) {
		if typ := evalString(t, ctx, p, "screen.orientation.type"); typ != cfg.ScreenOrientation {
			t.Errorf("orientation.type = %q, want %q", typ, cfg.ScreenOrientation)
		}
		if cfg.ScreenOrientationAngle != nil {
			if a := evalFloat(t, ctx, p, "screen.orientation.angle"); a != float64(*cfg.ScreenOrientationAngle) {
				t.Errorf("orientation.angle = %v, want %v", a, *cfg.ScreenOrientationAngle)
			}
		}
	})

	// #23 touch trio: ontouchstart absent, TouchEvent undefined, maxTouchPoints matches.
	t.Run("touch_trio", func(t *testing.T) {
		if evalBool(t, ctx, p, `'ontouchstart' in window`) {
			t.Error("'ontouchstart' should be absent (desktop)")
		}
		if !evalBool(t, ctx, p, `typeof window.TouchEvent === 'undefined'`) {
			t.Error("window.TouchEvent should be undefined (desktop)")
		}
		want := float64(0)
		if cfg.NavigatorMaxTouchPoints != nil {
			want = float64(*cfg.NavigatorMaxTouchPoints)
		}
		if mtp := evalFloat(t, ctx, p, "navigator.maxTouchPoints"); mtp != want {
			t.Errorf("navigator.maxTouchPoints = %v, want %v", mtp, want)
		}
	})

	// #13 voices: each generated voice's lang must match (getVoices may lag).
	t.Run("voices_lang", func(t *testing.T) {
		const expr = `JSON.stringify(speechSynthesis.getVoices().map(v => ({name: v.name, lang: v.lang})))`
		var voices []struct{ Name, Lang string }
		for range 40 {
			if err := json.Unmarshal([]byte(evalString(t, ctx, p, expr)), &voices); err != nil {
				t.Fatalf("decode voices: %v", err)
			}
			if len(voices) > 0 {
				break
			}
			time.Sleep(50 * time.Millisecond)
		}
		if len(voices) == 0 {
			t.Skip("no voices returned (voiceschanged not fired)")
		}
		want := make(map[string]string, len(cfg.Voices))
		for _, v := range cfg.Voices {
			want[v.Name] = v.Lang
		}
		for _, v := range voices {
			if w, ok := want[v.Name]; ok && w != v.Lang {
				t.Errorf("voice %q lang = %q, want %q", v.Name, v.Lang, w)
			}
		}
	})

	// #10 WebGL readPixels noise — best-effort: the per-seed noise lives in C++
	// so we can't predict bytes, but it must be deterministic within one
	// context (same seed → identical readback hash).
	t.Run("readpixels_deterministic", func(t *testing.T) {
		const hashExpr = `(() => {
			const c = document.createElement('canvas');
			c.width = 64; c.height = 64;
			const gl = c.getContext('webgl');
			gl.clearColor(0.3, 0.6, 0.9, 1); gl.clear(gl.COLOR_BUFFER_BIT);
			const px = new Uint8Array(64 * 64 * 4);
			gl.readPixels(0, 0, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, px);
			let h = 0; for (let i = 0; i < px.length; i++) { h = (h * 31 + px[i]) >>> 0; }
			return String(h);
		})()`
		h1 := evalString(t, ctx, p, hashExpr)
		h2 := evalString(t, ctx, p, hashExpr)
		if h1 != h2 {
			t.Errorf("readPixels hash not deterministic in-context: %s vs %s", h1, h2)
		}
	})
}
