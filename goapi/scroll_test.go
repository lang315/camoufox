package camoufox_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestScrollToBottom(t *testing.T) {
	bin := browserBinary(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body style="height:5000px;margin:0">
<div id="top">top</div>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(bin),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, err := b.NewContext(ctx)
	if err != nil {
		t.Fatalf("context: %v", err)
	}
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatalf("page: %v", err)
	}
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	if err := p.ScrollToBottom(ctx, camoufox.ScrollToBottomOptions{
		MaxSteps:  20,
		IdleMs:    50 * time.Millisecond,
		StepDelta: 500,
	}); err != nil {
		t.Fatalf("ScrollToBottom: %v", err)
	}

	// The bottom depends on the drawn window's innerHeight, so read it from the page.
	raw, err := p.Evaluate(ctx, `[window.scrollY, document.documentElement.scrollHeight - window.innerHeight]`)
	if err != nil {
		t.Fatalf("evaluate scrollY: %v", err)
	}
	got, _ := raw.([]any)
	if len(got) != 2 {
		t.Fatalf("evaluate scrollY: got %v", raw)
	}
	scrollY, _ := got[0].(float64)
	bottom, _ := got[1].(float64)
	if bottom <= 0 {
		t.Fatalf("the 5000px page is not scrollable: scrollHeight - innerHeight = %v", bottom)
	}
	if scrollY < bottom {
		t.Errorf("expected scrollY at the bottom (%v), got %v", bottom, scrollY)
	}
}

func TestScrollToAndBy(t *testing.T) {
	bin := browserBinary(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body style="height:3000px"></body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(bin),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatalf("launch: %v", err)
	}
	defer b.Close()

	bc, _ := b.NewContext(ctx)
	p, _ := bc.NewPage(ctx)
	defer p.Close(ctx)

	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad}); err != nil {
		t.Fatalf("goto: %v", err)
	}

	if err := p.ScrollTo(ctx, camoufox.ScrollToOptions{Y: 500}); err != nil {
		t.Fatalf("ScrollTo: %v", err)
	}
	if err := p.ScrollBy(ctx, 0, 200); err != nil {
		t.Fatalf("ScrollBy: %v", err)
	}

	raw, _ := p.Evaluate(ctx, `window.scrollY`)
	scrollY, _ := raw.(float64)
	if scrollY < 600 {
		t.Errorf("expected scrollY >= 600 after ScrollTo(500)+ScrollBy(200), got %v", scrollY)
	}
}
