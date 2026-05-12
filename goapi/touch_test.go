package camoufox_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

func TestTouchscreenTap(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<div id="out"></div>
<script>
document.addEventListener('touchstart', function(e) {
  document.getElementById('out').textContent = 'touched';
});
</script>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true),
		camoufox.WithFirefoxUserPref("dom.w3c_touch_events.enabled", 1))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}

	// Enable touch capability for this context.
	hasTouch := true
	if err := bc.SetTouchOverride(ctx, &hasTouch); err != nil {
		t.Fatalf("SetTouchOverride: %v", err)
	}

	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	if err := p.Touchscreen().Tap(ctx, 100, 100); err != nil {
		if strings.Contains(err.Error(), "sendTouchEvent is not a function") {
			t.Skip("Camoufox build lacks windowUtils.sendTouchEvent; touch events unsupported on this platform")
		}
		t.Fatalf("Tap: %v", err)
	}

	got, err := p.Evaluate(ctx, `document.getElementById('out').textContent`)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if got != "touched" {
		t.Errorf("expected 'touched', got %v", got)
	}
}

func TestTouchscreenTouchEvents(t *testing.T) {
	if os.Getenv("CAMOUFOX_BIN") == "" {
		t.Skip("set CAMOUFOX_BIN to run")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body>
<div id="log"></div>
<script>
var log = [];
['touchstart','touchmove','touchend','touchcancel'].forEach(function(e) {
  document.addEventListener(e, function() { log.push(e); });
});
window.getLog = function() { return log.join(','); };
</script>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true),
		camoufox.WithFirefoxUserPref("dom.w3c_touch_events.enabled", 1))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	hasTouch := true
	if err := bc.SetTouchOverride(ctx, &hasTouch); err != nil {
		t.Fatalf("SetTouchOverride: %v", err)
	}

	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 10 * time.Second}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	pt := []juggler.TouchPoint{{X: 50, Y: 50}}
	ts := p.Touchscreen()
	for _, fn := range []func() error{
		func() error { return ts.TouchStart(ctx, pt) },
		func() error { return ts.TouchMove(ctx, pt) },
		func() error { return ts.TouchEnd(ctx, pt) },
	} {
		if err := fn(); err != nil {
			if strings.Contains(err.Error(), "sendTouchEvent is not a function") {
				t.Skip("Camoufox build lacks windowUtils.sendTouchEvent; touch events unsupported on this platform")
			}
			t.Fatalf("touch event: %v", err)
		}
	}

	got, err := p.Evaluate(ctx, `window.getLog()`)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	want := "touchstart,touchmove,touchend"
	if fmt.Sprintf("%v", got) != want {
		t.Errorf("expected %q, got %v", want, got)
	}
}
