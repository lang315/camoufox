package camoufox_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
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
		// The listeners record into the DOM, not into a page global. Evaluate
		// runs in an isolated world -- that is the point of the juggler patch --
		// so it can read the DOM but never the page's own JS globals. Reading a
		// page global here would only pass on a build whose isolation is broken.
		_, _ = w.Write([]byte(`<html><body>
<div id="log"></div>
<script>
['touchstart','touchmove','touchend','touchcancel'].forEach(function(e) {
  document.addEventListener(e, function() {
    var d = document.getElementById('log');
    d.textContent = d.textContent ? d.textContent + ',' + e : e;
  });
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
			t.Fatalf("touch event: %v", err)
		}
	}

	got, err := p.Evaluate(ctx, `document.getElementById('log').textContent`)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	want := "touchstart,touchmove,touchend"
	if fmt.Sprintf("%v", got) != want {
		t.Errorf("expected %q, got %v", want, got)
	}
}
